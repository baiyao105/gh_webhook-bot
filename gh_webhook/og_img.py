"""
OG图片处理
"""

import asyncio
import hashlib
import os
import time
from collections import OrderedDict
from threading import Lock
from typing import Any, Dict, Optional
from urllib.parse import urljoin, urlparse

import aiofiles
import aiohttp
from bs4 import BeautifulSoup
from PIL import Image
from loguru import logger


class OGImageManager:
    """OG图片管理器"""

    def __init__(self, cache_dir: str, image_cache_days: int = 4):
        self.cache_dir = cache_dir
        self.image_cache_dir = os.path.join(cache_dir, "images")
        self.image_cache_days = image_cache_days
        self.image_cache = OrderedDict()
        self.cache_lock = Lock()
        self.async_lock = asyncio.Lock()
        os.makedirs(self.image_cache_dir, exist_ok=True)
        self._load_image_cache()

    def _load_image_cache(self):
        """加载图片缓存索引"""
        cache_file = os.path.join(self.cache_dir, "image_cache.json")
        try:
            if os.path.exists(cache_file):
                import json

                with open(cache_file, "r", encoding="utf-8") as f:
                    cache_data = json.load(f)
                # 验证缓存文件是否存在
                valid_cache = {}
                for url, info in cache_data.items():
                    cache_path = info.get("cache_path")
                    if cache_path and os.path.exists(cache_path):
                        valid_cache[url] = info

                self.image_cache = OrderedDict(valid_cache)
                logger.success(f"加载图片缓存: {len(self.image_cache)}个条目")
            else:
                self.image_cache = OrderedDict()
                logger.success("创建新的缓存器")
        except Exception as e:
            logger.error(f"加载图片缓存失败: {e}")
            self.image_cache = OrderedDict()

    async def _save_image_cache(self):
        """保存图片缓存索引"""
        cache_file = os.path.join(self.cache_dir, "image_cache.json")
        temp_file = cache_file + ".tmp"

        try:
            import json

            async with aiofiles.open(temp_file, "w", encoding="utf-8") as f:
                await f.write(json.dumps(dict(self.image_cache), indent=2, ensure_ascii=False))
            if os.path.exists(cache_file):
                os.remove(cache_file)
            os.rename(temp_file, cache_file)
            # logger.debug("图片缓存索引保存成功")
        except Exception as e:
            logger.error(f"保存图片缓存索引失败: {e}")
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except:
                    pass

    def _get_cache_key(self, url: str) -> str:
        """生成缓存键"""
        return hashlib.md5(url.encode("utf-8")).hexdigest()

    def _is_valid_url(self, url: str) -> bool:
        """验证URL是否有效"""
        if not url or not isinstance(url, str):
            return False

        try:
            result = urlparse(url)
            return all([result.scheme, result.netloc]) and result.scheme in [
                "http",
                "https",
            ]
        except Exception:
            return False

    async def _extract_og_image_from_html(self, html_content: str, base_url: str) -> Optional[str]:
        """从HTML内容中提取OG图片URL"""
        try:
            soup = BeautifulSoup(html_content, "html.parser")
            # 查找OG图片
            og_image = soup.find("meta", property="og:image")
            if og_image and og_image.get("content"):
                image_url = og_image["content"]
                return urljoin(base_url, image_url)
            # fallback：Twitter卡片图片
            twitter_image = soup.find("meta", attrs={"name": "twitter:image"})
            if twitter_image and twitter_image.get("content"):
                image_url = twitter_image["content"]
                return urljoin(base_url, image_url)
            # fallback：查找第一个较大的图片
            images = soup.find_all("img")
            for img in images:
                src = img.get("src")
                if src:
                    if any(keyword in src.lower() for keyword in ["icon", "logo", "avatar", "thumb"]):
                        continue
                    return urljoin(base_url, src)
            return None
        except Exception as e:
            logger.error(f"解析HTML提取OG图片失败: {e}")
            return None

    def _resize_image(
        self,
        image_path: str,
        target_width: int = 1600,
        target_height: int = 1200,
        quality: int = 85,
    ) -> bool:
        """调整图片大小"""
        try:
            with Image.open(image_path) as img:
                # 转RGB
                if img.mode in ("RGBA", "LA", "P"):
                    background = Image.new("RGB", img.size, (255, 255, 255))
                    if img.mode == "P":
                        img = img.convert("RGBA")
                    background.paste(img, mask=img.split()[-1] if img.mode == "RGBA" else None)
                    img = background
                elif img.mode != "RGB":
                    img = img.convert("RGB")
                original_width, original_height = img.size
                if original_width <= target_width and original_height <= target_height:
                    return True
                # 调整缩放比例
                width_ratio = target_width / original_width
                height_ratio = target_height / original_height
                scale_ratio = min(width_ratio, height_ratio)
                new_width = int(original_width * scale_ratio)
                new_height = int(original_height * scale_ratio)
                resized_img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                resized_img.save(image_path, "JPEG", quality=quality, optimize=True)
                logger.debug(f"图片已调整: {original_width}x{original_height} -> {new_width}x{new_height}")
                return True

        except Exception as e:
            logger.error(f"调整图片大小失败: {e}")
            return False

    async def _download_image(self, image_url: str, save_path: str, proxy_config: Optional[Dict] = None) -> bool:
        """下载图片"""
        try:
            timeout = aiohttp.ClientTimeout(total=30, connect=10)

            async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(), timeout=timeout) as session:
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
                }

                proxy_url = None
                if proxy_config and proxy_config.get("enabled"):
                    proxy_url = proxy_config.get("url")

                async with session.get(image_url, headers=headers, proxy=proxy_url) as response:
                    if response.status == 200:
                        content_type = response.headers.get("content-type", "").lower()
                        if not content_type.startswith("image/"):
                            logger.warning(f"URL返回的不是图片类型: {content_type}")
                            return False
                        content_length = response.headers.get("content-length")
                        if content_length and int(content_length) > 50 * 1024 * 1024:  # 50MB限制
                            logger.warning(f"图片文件过大: {content_length} bytes")
                            return False
                        async with aiofiles.open(save_path, "wb") as f:
                            async for chunk in response.content.iter_chunked(8192):
                                await f.write(chunk)
                        file_size = os.path.getsize(save_path)
                        if file_size == 0:
                            logger.warning("下载的图片文件为空")
                            os.remove(save_path)
                            return False
                        logger.debug(f"图片下载成功: {file_size} bytes")
                        return True
                    else:
                        logger.warning(f"下载图片失败, 状态码: {response.status}")
                        return False

        except Exception as e:
            logger.error(f"下载图片异常: {e}")
            if os.path.exists(save_path):
                try:
                    os.remove(save_path)
                except:
                    pass
            return False

    async def get_og_image(
        self, url: str, force_refresh: bool = False, proxy_config: Optional[Dict] = None
    ) -> Optional[str]:
        """
        获取URL的Open Graph图片

        Args:
            url: 目标URL
            force_refresh: 是否强制刷新缓存
            proxy_config: 代理配置

        Returns:
            str: 缓存的图片文件路径, 如果失败返回None
        """
        if not self._is_valid_url(url):
            logger.warning(f"无效的URL: {url}")
            return None
        cache_key = self._get_cache_key(url)
        current_time = time.time()
        # 检查缓存
        if not force_refresh and cache_key in self.image_cache:
            cache_info = self.image_cache[cache_key]
            cache_path = cache_info.get("cache_path")
            cache_time = cache_info.get("timestamp", 0)
            if (current_time - cache_time) < (self.image_cache_days * 24 * 3600):
                if cache_path and os.path.exists(cache_path):
                    logger.debug(f"使用缓存的OG图片: {url}")
                    with self.cache_lock:
                        self.image_cache.move_to_end(cache_key)
                    return cache_path

        async with self.async_lock:
            try:
                timeout = aiohttp.ClientTimeout(total=30, connect=10)
                async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(), timeout=timeout) as session:
                    headers = {
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
                    }

                    proxy_url = None
                    if proxy_config and proxy_config.get("enabled"):
                        proxy_url = proxy_config.get("url")
                    async with session.get(url, headers=headers, proxy=proxy_url) as response:
                        if response.status != 200:
                            logger.warning(f"获取网页失败, 状态码: {response.status}")
                            return None

                        html_content = await response.text()

                image_url = await self._extract_og_image_from_html(html_content, url)
                if not image_url:
                    logger.info(f"未找到OG图片: {url}")
                    return None
                file_extension = ".jpg"  # 保存为jpg
                cache_filename = f"{cache_key}{file_extension}"
                cache_path = os.path.join(self.image_cache_dir, cache_filename)
                if await self._download_image(image_url, cache_path, proxy_config):
                    self._resize_image(cache_path)
                    with self.cache_lock:
                        self.image_cache[cache_key] = {
                            "url": url,
                            "image_url": image_url,
                            "cache_path": cache_path,
                            "timestamp": current_time,
                            "file_size": os.path.getsize(cache_path),
                        }
                        while len(self.image_cache) > 1000:
                            oldest_key, oldest_info = self.image_cache.popitem(last=False)
                            old_path = oldest_info.get("cache_path")
                            if old_path and os.path.exists(old_path):
                                try:
                                    os.remove(old_path)
                                except:
                                    pass
                    await self._save_image_cache()
                    logger.info(f"OG图片获取成功: {url} -> {cache_path}")
                    return cache_path
                else:
                    logger.warning(f"下载OG图片失败: {image_url}")
                    return None
            except Exception as e:
                logger.error(f"获取OG图片异常: {e}")
                return None

    def clear_url_cache(self, url: str):
        """清除指定URL的缓存"""
        cache_key = self._get_cache_key(url)

        with self.cache_lock:
            if cache_key in self.image_cache:
                cache_info = self.image_cache.pop(cache_key)
                cache_path = cache_info.get("cache_path")

                if cache_path and os.path.exists(cache_path):
                    try:
                        os.remove(cache_path)
                        logger.info(f"已清除URL缓存: {url}")
                    except Exception as e:
                        logger.error(f"删除缓存文件失败: {e}")

    def clean_expired_cache(self) -> int:
        """清理过期缓存"""
        current_time = time.time()
        expired_keys = []
        with self.cache_lock:
            for key, info in self.image_cache.items():
                cache_time = info.get("timestamp", 0)
                if (current_time - cache_time) > (self.image_cache_days * 24 * 3600):
                    expired_keys.append(key)
            # 删除过期缓存
            for key in expired_keys:
                cache_info = self.image_cache.pop(key, {})
                cache_path = cache_info.get("cache_path")
                if cache_path and os.path.exists(cache_path):
                    try:
                        os.remove(cache_path)
                    except Exception as e:
                        logger.error(f"删除过期缓存文件失败: {e}")
        if expired_keys:
            try:
                loop = asyncio.get_event_loop()
                loop.create_task(self._save_image_cache())
            except:
                pass

            logger.info(f"清理过期OG图片缓存: {len(expired_keys)}个")

        return len(expired_keys)

    def get_cache_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        with self.cache_lock:
            total_size = 0
            for info in self.image_cache.values():
                total_size += info.get("file_size", 0)
            return {
                "total_items": len(self.image_cache),
                "total_size_bytes": total_size,
                "total_size_mb": total_size / (1024 * 1024),
                "cache_dir": self.image_cache_dir,
            }


# 全局OG图片管理器实例
_og_manager = None


def get_og_manager(cache_dir: str, image_cache_days: int = 4) -> OGImageManager:
    """获取全局OG图片管理器实例"""
    global _og_manager
    if _og_manager is None:
        _og_manager = OGImageManager(cache_dir, image_cache_days)
    return _og_manager


def cleanup_og_manager():
    """清理OG图片管理器资源"""
    global _og_manager
    if _og_manager:
        # 没啥用嗯...
        _og_manager = None
