"""本机配置入口：读取环境变量与.env，不把凭证传给前端。

环境变量优先于.env；配置在进程启动时加载，修改后需要重启API。
"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

APP_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(APP_ROOT / '.env', override=False)


@dataclass(frozen=True)
class Settings:
    """API、存储与模型适配器共享的只读配置。"""
    database_path: str = os.getenv('ANXIN_DATABASE_PATH') or str(APP_ROOT / 'runtime' / 'anxin.db')
    model_base_url: str = os.getenv('MODEL_BASE_URL', '').rstrip('/')
    model_name: str = os.getenv('MODEL_NAME', '')
    model_api_key: str = os.getenv('MODEL_API_KEY', '')
    model_timeout: float = float(os.getenv('MODEL_TIMEOUT_SECONDS') or '35')

    @property
    def model_configured(self) -> bool:
        """只说明必需配置存在，不能替代真实API调用验收。"""
        return bool(self.model_base_url and self.model_name and self.model_api_key)


settings = Settings()
