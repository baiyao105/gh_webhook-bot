"""
API模块
"""

import asyncio
import json
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Callable, Dict, Optional

import uvicorn
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from loguru import logger
from pydantic import BaseModel


class WebhookResponse(BaseModel):
    """Webhook响应模型"""

    status: str = "success"
    message: str = "Webhook received"
    timestamp: str = ""
    delivery_id: Optional[str] = None


class APIServer:
    """API服务类"""

    def __init__(self, config_manager, webhook_handler=None):
        self.config_manager = config_manager
        self.webhook_handler = webhook_handler
        self.app = None
        self.server = None
        self.server_thread = None
        self.is_running = False
        self.startup_callbacks = []
        self.shutdown_callbacks = []
        self.host = "0.0.0.0"
        self.port = 5000
        self.debug = False

        self._load_server_config()

    def _load_server_config(self):
        """加载服务器配置"""
        try:
            self.port = self.config_manager.get("port", 8000)
            webhook_config = self.config_manager.get("webhook", {})
            self.host = webhook_config.get("host", "0.0.0.0")
            self.debug = webhook_config.get("debug", False)
        except Exception as e:
            logger.error(f"加载服务器配置失败: {e}")

    def add_startup_callback(self, callback: Callable):
        """添加启动回调"""
        self.startup_callbacks.append(callback)

    def add_shutdown_callback(self, callback: Callable):
        """添加关闭回调"""
        self.shutdown_callbacks.append(callback)

    def create_app(self) -> FastAPI:
        """创建FastAPI应用"""

        @asynccontextmanager
        async def lifespan(app: FastAPI):
            """应用生命周期管理"""
            for callback in self.startup_callbacks:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback()
                    else:
                        callback()
                except Exception as e:
                    logger.error(f"启动回调执行失败: {e}")
            # logger.success("服务器启动完成")

            yield

            # 关闭时执行
            logger.info("服务器关闭中...")
            for callback in self.shutdown_callbacks:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback()
                    else:
                        callback()
                except Exception as e:
                    logger.error(f"关闭回调执行失败: {e}")
            # logger.info("服务器关闭完成")

        app = FastAPI(
            title="GitHub Webhook Bot API",
            description="webhook消息调度器",
            version="1.0.0",
            lifespan=lifespan,
        )

        self._setup_middleware(app)
        self._register_routes(app)

        return app

    def _setup_middleware(self, app: FastAPI):
        """中间件"""
        app.add_middleware(GZipMiddleware, minimum_size=1000)
        trusted_hosts = self.config_manager.get("webhook.trusted_hosts", ["*"])
        if trusted_hosts and trusted_hosts != ["*"]:
            app.add_middleware(TrustedHostMiddleware, allowed_hosts=trusted_hosts)
        cors_config = self.config_manager.get("webhook.cors", {})
        if cors_config.get("enabled", True):
            app.add_middleware(
                CORSMiddleware,
                allow_origins=cors_config.get("origins", ["*"]),
                allow_credentials=cors_config.get("credentials", True),
                allow_methods=cors_config.get("methods", ["*"]),
                allow_headers=cors_config.get("headers", ["*"]),
            )

    def _register_routes(self, app: FastAPI):
        """注册路由"""

        @app.get("/")
        async def root():
            """根路径"""
            return {
                "service": "GitHub Webhook Bot",
                "version": "1.0.0",
                "status": "running",
                "timestamp": datetime.now().isoformat(),
            }

        @app.post("/webhook")
        async def webhook_endpoint(request: Request, background_tasks: BackgroundTasks):
            """Webhook接收端点"""
            if not self.webhook_handler:
                raise HTTPException(status_code=503, detail="Webhook handler not available")

            try:
                body = await request.body()
                headers = dict(request.headers)
                event_type = headers.get("x-github-event", "")
                delivery_id = headers.get("x-github-delivery", "")
                signature = headers.get("x-hub-signature-256") or headers.get("x-hub-signature", "")
                if not event_type:
                    raise HTTPException(status_code=400, detail="Missing X-GitHub-Event header")
                if not delivery_id:
                    raise HTTPException(status_code=400, detail="Missing X-GitHub-Delivery header")
                try:
                    payload = json.loads(body.decode("utf-8"))
                except json.JSONDecodeError:
                    raise HTTPException(status_code=400, detail="Invalid JSON payload")

                webhook_data = {
                    "event_type": event_type,
                    "delivery_id": delivery_id,
                    "signature": signature,
                    "payload": payload,
                    "headers": headers,
                    "timestamp": datetime.now().isoformat(),
                    "raw_body": body,  # 原始数据用于签名验证
                }
                background_tasks.add_task(self._process_webhook_background, webhook_data)
                return WebhookResponse(
                    status="accepted",
                    message=f"Webhook-{delivery_id} received and queued for processing",
                    timestamp=datetime.now().isoformat(),
                    delivery_id=delivery_id,
                )

            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Webhook处理异常: {e}")
                raise HTTPException(status_code=500, detail="Internal server error")

        # 原先留下的烂尾楼api
        @app.get("/status")
        async def status():
            """状态"""
            return {
                "server": {
                    "running": self.is_running,
                    "host": self.host,
                    "port": self.port,
                    "debug": self.debug,
                },
                "webhook": {
                    "handler_available": self.webhook_handler is not None,
                    "enabled_repos": list(self.config_manager.get("repositories", {}).keys()),
                },
                "timestamp": datetime.now().isoformat(),
            }

        @app.get("/webhook/test")
        async def webhook_test():
            """Webhook测试端点"""
            return {
                "message": "Webhook endpoint is working",
                "timestamp": datetime.now().isoformat(),
                "handler_available": self.webhook_handler is not None,
            }

        # @app.post("/api/config/reload")
        # async def reload_config():
        #     """重新加载配置"""
        #     try:
        #         self.config_manager.ConfigHandler.on_modified()
        #         self._load_server_config()
        #         return {
        #             "status": "success",
        #             "message": "Configuration reloaded",
        #             "timestamp": datetime.now().isoformat(),
        #         }
        #     except Exception as e:
        #         logger.error(f"重新加载配置失败: {e}")
        #         raise HTTPException(status_code=500, detail=str(e))

        # @app.get("/api/config")
        # async def get_config():
        #     """获取配置信息"""
        #     try:
        #         config = self.config_manager.get_all_config()
        #         # 脱敏处理
        #         sanitized_config = self._sanitize_config(config)
        #         return {"config": sanitized_config, "timestamp": datetime.now().isoformat()}
        #     except Exception as e:
        #         logger.error(f"获取配置失败: {e}")
        #         raise HTTPException(status_code=500, detail=str(e))

        # @app.get("/api/repositories")
        # async def get_repositories():
        #     """获取仓库列表"""
        #     try:
        #         repositories = self.config_manager.get("repositories", {})
        #         repo_list = []
        #         for repo_name, repo_config in repositories.items():
        #             repo_info = {
        #                 "name": repo_name,
        #                 "enabled": repo_config.get("enabled", True),
        #                 "webhook_enabled": repo_config.get("webhook", {}).get("enabled", True),
        #                 "notification_channels": len(repo_config.get("notifications", {}).get("channels", [])),
        #                 "has_github_token": bool(repo_config.get("github", {}).get("token")),
        #                 "ai_review_enabled": repo_config.get("ai", {}).get("enabled", False),
        #             }
        #             repo_list.append(repo_info)
        #         return {"repositories": repo_list, "total": len(repo_list), "timestamp": datetime.now().isoformat()}
        #     except Exception as e:
        #         logger.error(f"获取仓库列表失败: {e}")
        #         raise HTTPException(status_code=500, detail=str(e))

        # 错误处理(基本用不上
        @app.exception_handler(404)
        async def not_found_handler(request: Request, exc):
            return JSONResponse(
                status_code=404,
                content={
                    "error": "Not Found",
                    "message": f"Path {request.url.path} not found",
                    "timestamp": datetime.now().isoformat(),
                },
            )

        @app.exception_handler(500)
        async def internal_error_handler(request: Request, exc):
            logger.error(f"内部服务器错误: {exc}")
            return JSONResponse(
                status_code=500,
                content={
                    "error": "Internal Server Error",
                    "message": "An internal error occurred",
                    "timestamp": datetime.now().isoformat(),
                },
            )

    async def _process_webhook_background(self, webhook_data: Dict[str, Any]):
        """处理webhook(后台)"""
        try:
            if self.webhook_handler:
                await self.webhook_handler.process_webhook(webhook_data)
        except Exception as e:
            logger.error(f"处理webhook异常: {e}")

    def _sanitize_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """脱敏配置信息"""
        sanitized = {}

        for key, value in config.items():
            if isinstance(value, dict):
                sanitized[key] = self._sanitize_config(value)
            elif key.lower() in ["token", "secret", "password", "key", "api_key"]:
                if isinstance(value, str) and len(value) > 8:  # 脱敏
                    sanitized[key] = value[:4] + "*" * (len(value) - 8) + value[-4:]
                else:
                    sanitized[key] = "***"
            else:
                sanitized[key] = value

        return sanitized

    def start_server(self) -> bool:
        """启动服务器"""
        if self.is_running:
            logger.warning("服务器已在运行中")
            return True

        try:
            self.app = self.create_app()
            self._start_time = time.time()
            config = uvicorn.Config(
                app=self.app,
                host=self.host,
                port=self.port,
                server_header=False,
                log_level="info" if self.debug else "warning",
                access_log=self.debug,
                loop="asyncio",
            )
            self.server = uvicorn.Server(config)

            # 启动服务器
            self.server_thread = threading.Thread(target=self._run_server, name="APIServer", daemon=True)
            self.server_thread.start()
            max_wait = 10
            wait_time = 0
            while not self.is_running and wait_time < max_wait:
                time.sleep(0.1)
                wait_time += 0.1

            if self.is_running:
                logger.success(f"服务器启动成功: http://{self.host}:{self.port}")
                return True
            else:
                logger.error("服务器启动超时")
                return False

        except Exception as e:
            logger.error(f"服务器启动失败: {e}")
            return False

    def _run_server(self):
        """运行服务器(独立线程)"""
        try:
            # 创建新的事件循环
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self.is_running = True
            loop.run_until_complete(self.server.serve())
        except Exception as e:
            logger.error(f"服务器运行异常: {e}")

        finally:
            self.is_running = False
            logger.info("服务器线程结束")

    def stop_server(self) -> bool:
        """停止服务器"""
        if not self.is_running:
            logger.warning("服务器未在运行")
            return True

        try:
            logger.debug("正在停止服务器...")
            if self.server:
                self.server.should_exit = True
            if self.server_thread and self.server_thread.is_alive():
                self.server_thread.join(timeout=5)

            self.is_running = False
            logger.info("服务器已停止")
            return True

        except Exception as e:
            logger.error(f"停止服务器失败: {e}")
            return False

    def restart_server(self) -> bool:
        """重启服务器"""
        logger.debug("重启服务器...")
        if not self.stop_server():
            return False
        time.sleep(1)  # 等待一下
        self._load_server_config()
        return self.start_server()

    def get_server_info(self) -> Dict[str, Any]:
        """获取服务器信息"""
        return {
            "running": self.is_running,
            "host": self.host,
            "port": self.port,
            "debug": self.debug,
            "url": f"http://{self.host}:{self.port}" if self.is_running else None,
            "webhook_url": (f"http://{self.host}:{self.port}/webhook" if self.is_running else None),
            "uptime": (time.time() - getattr(self, "_start_time", time.time()) if self.is_running else 0),
        }

    def set_webhook_handler(self, handler):
        """设置webhook处理器"""
        self.webhook_handler = handler
        logger.info("处理器已设置")


# 全局服务器实例
_api_server = None


def get_api_server(config_manager, webhook_handler=None) -> APIServer:
    """获取全局服务器实例"""
    global _api_server
    if _api_server is None:
        _api_server = APIServer(config_manager, webhook_handler)
    elif webhook_handler:
        _api_server.set_webhook_handler(webhook_handler)
    return _api_server


def cleanup_api_server():
    """清理服务器资源"""
    global _api_server
    if _api_server:
        _api_server.stop_server()
        _api_server = None
