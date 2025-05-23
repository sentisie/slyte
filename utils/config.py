import os
import yaml
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

class Config:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Config, cls).__new__(cls)
            cls._instance._config = None
            cls._instance.load_config()
        return cls._instance
    
    def load_config(self):
        """Load configuration from config.yaml file"""
        config_path = os.getenv('CONFIG_PATH', 'config.yaml')
        
        if not os.path.exists(config_path):
            logger.error(f"Configuration file not found: {config_path}")
            raise FileNotFoundError(f"Configuration file not found: {config_path}")
        
        try:
            with open(config_path, 'r') as f:
                self._config = yaml.safe_load(f)
            logger.info(f"Configuration loaded from {config_path}")
        except Exception as e:
            logger.error(f"Error loading configuration: {e}")
            raise
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value by key (support nested keys with dots)"""
        if not self._config:
            self.load_config()
            
        keys = key.split('.')
        value = self._config
        
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
                
        return value
    
    def get_bot_token(self) -> str:
        """Get bot token from config"""
        return self.get('bot.token')
    
    def get_admin_ids(self) -> List[int]:
        """Get admin IDs from config"""
        return self.get('bot.admin_ids', [])
    
    def get_servers(self) -> List[Dict[str, Any]]:
        """Get list of all servers"""
        return self.get('servers', [])
    
    def get_server_by_id(self, server_id: str) -> Optional[Dict[str, Any]]:
        """Get server configuration by server ID"""
        servers = self.get_servers()
        for server in servers:
            if server.get('id') == server_id:
                return server
        return None
    
    def get_default_server(self) -> Optional[Dict[str, Any]]:
        """Get default server (first in list)"""
        servers = self.get_servers()
        if servers:
            return servers[0]
        return None
    
    def get_server_details(self, server_id: str = None) -> Dict[str, Any]:
        """Get server details by ID, or default if ID not specified"""
        if server_id:
            server = self.get_server_by_id(server_id)
            if server:
                return server
        
        # Обратная совместимость со старой конфигурацией
        legacy_server = self.get('server', {})
        if legacy_server:
            return legacy_server
            
        # Если нет старой конфигурации, возвращаем первый сервер
        server = self.get_default_server()
        if server:
            return server
            
        return {}
    
    def get_xray_config(self, server_id: str = None) -> Dict[str, Any]:
        """Get Xray configuration for specific server or default"""
        server = self.get_server_details(server_id)
        
        # Проверяем, есть ли xray в конфигурации сервера
        if 'xray' in server:
            return server.get('xray', {})
        
        # Обратная совместимость
        return self.get('xray', {})
    
    def get_payment_config(self) -> Dict[str, Any]:
        """Get payment configuration"""
        return self.get('payments', {})
    
    def get_subscription_plans(self) -> List[Dict[str, Any]]:
        """Get subscription plans"""
        return self.get('subscription_plans', [])
    
    def is_payment_enabled(self) -> bool:
        """Check if payment is enabled"""
        return self.get('payments.enabled', False)
    
    def get_crypto_bot_token(self) -> Optional[str]:
        """Get CryptoBot token if configured"""
        return self.get('payments.crypto_bot_token')
    
    def is_auto_generate_keys_enabled(self) -> bool:
        """Check if auto generation of keys is enabled"""
        return self.get('payments.auto_generate_keys', True)
    
    def is_trial_enabled(self) -> bool:
        """Check if trial period is enabled"""
        return self.get('trial.enabled', False)
    
    def get_trial_days(self) -> int:
        """Get trial period duration in days"""
        return self.get('trial.days', 3)
    
    def is_telegram_stars_enabled(self) -> bool:
        """Check if payment with Telegram Stars is enabled"""
        return self.get('payments.telegram_stars_enabled', False)

# Create a singleton instance
config = Config() 