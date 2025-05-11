import os
import json
import uuid
import base64
import logging
import subprocess
from typing import Dict, List, Any, Optional, Tuple

from utils.config import config

logger = logging.getLogger(__name__)

class XRayManager:
    _instance = None
    _server_instances = {}
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(XRayManager, cls).__new__(cls)
            cls._instance._initialize_servers()
        return cls._instance
    
    def _initialize_servers(self):
        """Initialize managers for all servers"""
        # Получаем список всех серверов
        servers = config.get_servers()
        
        # Если сервера заданы через новый формат - servers
        if servers:
            for server in servers:
                server_id = server.get('id')
                if server_id:
                    self._server_instances[server_id] = ServerXRayManager(server_id)
        else:
            # Для обратной совместимости создаем экземпляр для сервера из корневых настроек
            self._server_instances['default'] = ServerXRayManager()
            
    def get_server_manager(self, server_id: str = None) -> 'ServerXRayManager':
        """Get XRay manager for specific server"""
        if server_id and server_id in self._server_instances:
            return self._server_instances[server_id]
        
        # Если сервер не указан или не найден, возвращаем первый в списке
        if self._server_instances:
            return next(iter(self._server_instances.values()))
        
        # Если нет ни одного сервера, создаем дефолтный
        return ServerXRayManager()
    
    def add_user(self, email: str, protocol: str = "reality", server_id: str = None) -> Dict[str, Any]:
        """Add user to specified server or default server"""
        server_mgr = self.get_server_manager(server_id)
        return server_mgr.add_user(email, protocol)
    
    def remove_user(self, email: str, server_id: str = None) -> bool:
        """Remove user from specified server"""
        server_mgr = self.get_server_manager(server_id)
        return server_mgr.remove_user(email)
    
    def get_user(self, email: str, server_id: str = None) -> Optional[Dict[str, Any]]:
        """Get user from specified server"""
        server_mgr = self.get_server_manager(server_id)
        return server_mgr.get_user(email)
    
    def get_all_users(self, server_id: str = None) -> List[Dict[str, Any]]:
        """Get all users from specified server"""
        server_mgr = self.get_server_manager(server_id)
        return server_mgr.get_all_users()
    
    def generate_vless_link(self, uuid: str, email: str, protocol: str = "reality", server_id: str = None) -> str:
        """Generate VLESS link for specified server"""
        server_mgr = self.get_server_manager(server_id)
        return server_mgr.generate_vless_link(uuid, email, protocol)
    
    def reload_xray(self, server_id: str = None) -> bool:
        """Reload XRay on specified server"""
        if server_id:
            # Перезагружаем только конкретный сервер
            server_mgr = self.get_server_manager(server_id)
            return server_mgr.reload_xray()
        else:
            # Перезагружаем все серверы
            results = []
            for server_id, server_mgr in self._server_instances.items():
                results.append(server_mgr.reload_xray())
            # Возвращаем True только если все серверы успешно перезагружены
            return all(results)
    
    def get_user_traffic(self, email: str, server_id: str = None) -> Dict[str, int]:
        """Get user traffic from specified server"""
        server_mgr = self.get_server_manager(server_id)
        return server_mgr.get_user_traffic(email)
    
    def reset_user_traffic(self, email: str, server_id: str = None) -> bool:
        """Reset user traffic on specified server"""
        server_mgr = self.get_server_manager(server_id)
        return server_mgr.reset_user_traffic(email)

    def get_available_servers(self) -> List[Dict[str, Any]]:
        """Get list of all available servers with basic info"""
        servers = []
        for server_id in self._server_instances.keys():
            server_config = config.get_server_by_id(server_id)
            if server_config:
                servers.append({
                    'id': server_id,
                    'name': server_config.get('name', f'Server {server_id}'),
                    'location': server_config.get('location', 'Unknown'),
                    'description': server_config.get('description', '')
                })
        return servers


class ServerXRayManager:
    """Manager for single XRay server instance"""
    
    def __init__(self, server_id = None):
        self.server_id = server_id
        
        # Загрузка конфигурации сервера
        server_config = config.get_server_details(server_id)
        xray_config = config.get_xray_config(server_id)
        
        self.config_path = xray_config.get('config_path', '/etc/xray/config.json')
        self.server_ip = server_config.get('ip')
        self.server_domain = server_config.get('domain')
        self.reality_port = server_config.get('reality_port', 443)
        self.ws_port = server_config.get('vless_port', 443)
        
        # Для доступа к reality настройкам напрямую из сервера
        if 'reality' in xray_config:
            self.reality_settings = xray_config.get('reality', {})
        else:
            # Обратная совместимость
            self.reality_settings = config.get('xray.reality', {})
        
        # Автоматическая генерация ключей, если включено
        if config.is_auto_generate_keys_enabled():
            self._init_reality_keys()
    
    def _init_reality_keys(self):
        """Initialize Reality keys if they are not set or auto-generation is enabled"""
        # Проверяем, есть ли уже ключи
        private_key = self.reality_settings.get('private_key', '')
        
        if not private_key or private_key == 'your_private_key_here':
            logger.info(f"Auto-generating Reality keys for server {self.server_id}...")
            
            # Генерируем новую пару ключей
            private_key, public_key = self.generate_keys()
            
            if private_key and public_key:
                # Генерируем short_id
                short_id = os.urandom(4).hex()
                
                # Обновляем настройки в памяти
                self.reality_settings['private_key'] = private_key
                self.reality_settings['public_key'] = public_key
                self.reality_settings['short_id'] = short_id
                
                logger.info(f"Reality keys generated successfully for server {self.server_id}")
            else:
                logger.error(f"Failed to generate Reality keys for server {self.server_id}")
    
    def load_config(self) -> Dict[str, Any]:
        """Load the current Xray configuration"""
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, 'r') as f:
                    return json.load(f)
            else:
                logger.warning(f"Xray config file not found at {self.config_path}. Creating default config.")
                return self._create_default_config()
        except Exception as e:
            logger.error(f"Error loading Xray config: {e}")
            return self._create_default_config()
    
    def save_config(self, config_data: Dict[str, Any]) -> bool:
        """Save the Xray configuration"""
        try:
            # Create directory if it doesn't exist
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            
            with open(self.config_path, 'w') as f:
                json.dump(config_data, f, indent=2)
            
            logger.info(f"Xray config saved to {self.config_path}")
            return True
        except Exception as e:
            logger.error(f"Error saving Xray config: {e}")
            return False
    
    def _create_default_config(self) -> Dict[str, Any]:
        """Create a default configuration for Xray"""
        default_config = {
            "log": {
                "loglevel": "warning",
                "access": "/var/log/xray/access.log",
                "error": "/var/log/xray/error.log"
            },
            "inbounds": [
                # Reality inbound
                {
                    "port": self.reality_port,
                    "protocol": "vless",
                    "tag": "vless-reality",
                    "settings": {
                        "clients": [],
                        "decryption": "none"
                    },
                    "streamSettings": {
                        "network": "tcp",
                        "security": "reality",
                        "realitySettings": {
                            "show": False,
                            "dest": self.reality_settings.get('dest', 'www.google.com:443'),
                            "serverNames": self.reality_settings.get('server_names', 
                                          ["www.microsoft.com", "www.amazon.com", "www.cloudflare.com"]),
                            "privateKey": self.reality_settings.get('private_key', ''),
                            "shortIds": [self.reality_settings.get('short_id', '')]
                        }
                    },
                    "sniffing": {
                        "enabled": True,
                        "destOverride": ["http", "tls"]
                    }
                },
                # WebSocket inbound
                {
                    "port": self.ws_port,
                    "protocol": "vless",
                    "tag": "vless-ws",
                    "settings": {
                        "clients": [],
                        "decryption": "none"
                    },
                    "streamSettings": {
                        "network": "ws",
                        "security": "tls",
                        "tlsSettings": {
                            "alpn": ["http/1.1"],
                            "certificates": [
                                {
                                    "certificateFile": "/path/to/fullchain.pem",
                                    "keyFile": "/path/to/privkey.pem"
                                }
                            ]
                        },
                        "wsSettings": {
                            "path": "/ws"
                        }
                    },
                    "sniffing": {
                        "enabled": True,
                        "destOverride": ["http", "tls"]
                    }
                },
                # API inbound for stats
                {
                    "listen": "127.0.0.1",
                    "port": 10085,
                    "protocol": "dokodemo-door",
                    "settings": {
                        "address": "127.0.0.1"
                    },
                    "tag": "api"
                }
            ],
            "outbounds": [
                {
                    "protocol": "freedom",
                    "tag": "direct"
                },
                {
                    "protocol": "blackhole",
                    "tag": "blocked"
                }
            ],
            "policy": {
                "levels": {
                    "0": {
                        "statsUserUplink": True,
                        "statsUserDownlink": True
                    }
                },
                "system": {
                    "statsInboundUplink": True,
                    "statsInboundDownlink": True
                }
            },
            "routing": {
                "domainStrategy": "AsIs",
                "rules": [
                    {
                        "type": "field",
                        "inboundTag": ["api"],
                        "outboundTag": "api"
                    },
                    {
                        "type": "field",
                        "outboundTag": "blocked",
                        "ip": ["geoip:private"]
                    },
                    {
                        "type": "field",
                        "outboundTag": "blocked",
                        "protocol": ["bittorrent"]
                    }
                ]
            },
            "stats": {},
            "api": {
                "tag": "api",
                "services": ["StatsService"]
            }
        }
        
        return default_config
    
    def generate_keys(self) -> Tuple[str, str]:
        """Generate a new key pair for Reality"""
        try:
            result = subprocess.run(
                ["xray", "x25519"],
                capture_output=True,
                text=True,
                check=True
            )
            output = result.stdout.strip().split('\n')
            private_key = output[0].split(":")[1].strip()
            public_key = output[1].split(":")[1].strip()
            
            return private_key, public_key
        except Exception as e:
            logger.error(f"Error generating keys: {e}")
            # Return some default values in case of error
            return "", ""
    
    def add_user(self, email: str, protocol: str = "reality") -> Dict[str, Any]:
        """
        Add a new user to Xray configuration
        
        Args:
            email: User identifier (email format recommended)
            protocol: 'reality' or 'websocket'
            
        Returns:
            User configuration including UUID
        """
        config_data = self.load_config()
        
        # Generate a UUID for the user
        user_id = str(uuid.uuid4())
        
        # Create user configuration
        user = {
            "id": user_id,
            "email": email,
            "flow": "xtls-rprx-vision" if protocol == "reality" else ""
        }
        
        # Find the correct inbound
        for inbound in config_data["inbounds"]:
            if (protocol == "reality" and "vless-reality" == inbound.get("tag")) or \
               (protocol == "websocket" and "vless-ws" == inbound.get("tag")):
                # Add user to this inbound
                inbound["settings"]["clients"].append(user)
        
        # Save configuration
        if self.save_config(config_data):
            # Reload XRay (optional, can be done separately)
            self.reload_xray()
            
            return {
                "id": user_id,
                "email": email,
                "protocol": protocol
            }
        
        return {"error": "Failed to add user"}
    
    def remove_user(self, email: str) -> bool:
        """Remove a user from both Reality and WebSocket inbounds"""
        config_data = self.load_config()
        removed = False
        
        # Check each inbound
        for inbound in config_data["inbounds"]:
            if "settings" in inbound and "clients" in inbound["settings"]:
                # Remove user from clients list
                clients = inbound["settings"]["clients"]
                new_clients = [c for c in clients if c.get("email") != email]
                
                if len(clients) != len(new_clients):
                    inbound["settings"]["clients"] = new_clients
                    removed = True
        
        if removed and self.save_config(config_data):
            # Reload XRay
            self.reload_xray()
            return True
            
        return False
    
    def get_user(self, email: str) -> Optional[Dict[str, Any]]:
        """Get user information by email"""
        config_data = self.load_config()
        
        for inbound in config_data["inbounds"]:
            if "settings" in inbound and "clients" in inbound["settings"]:
                for client in inbound["settings"]["clients"]:
                    if client.get("email") == email:
                        return {
                            "id": client.get("id"),
                            "email": email,
                            "protocol": "reality" if inbound.get("tag") == "vless-reality" else "websocket"
                        }
        
        return None
    
    def get_all_users(self) -> List[Dict[str, Any]]:
        """Get all users from configuration"""
        config_data = self.load_config()
        users = []
        
        for inbound in config_data["inbounds"]:
            if "settings" in inbound and "clients" in inbound["settings"]:
                protocol = "reality" if inbound.get("tag") == "vless-reality" else "websocket"
                
                for client in inbound["settings"]["clients"]:
                    users.append({
                        "id": client.get("id"),
                        "email": client.get("email"),
                        "protocol": protocol
                    })
        
        return users
    
    def generate_vless_link(self, uuid: str, email: str, protocol: str = "reality") -> str:
        """
        Generate a VLESS URL for client configuration
        
        Args:
            uuid: User UUID
            email: User email/identifier
            protocol: 'reality' or 'websocket'
        
        Returns:
            VLESS URL string
        """
        if protocol == "reality":
            # Create Reality link
            server_address = self.server_domain or self.server_ip
            if not server_address:
                return "Error: Server address not configured"
                
            params = {
                "security": "reality",
                "encryption": "none",
                "flow": "xtls-rprx-vision",
                "type": "tcp",
                "sni": self.reality_settings.get("server_names", ["www.microsoft.com"])[0],
                "fp": "chrome",
                "pbk": self.reality_settings.get("public_key", ""),
                "sid": self.reality_settings.get("short_id", "")
            }
            
            # Convert params to URL query string
            query_parts = []
            for key, value in params.items():
                if isinstance(value, list):
                    value = value[0]  # Use first item if list
                query_parts.append(f"{key}={value}")
            
            query_string = "&".join(query_parts)
            
            return f"vless://{uuid}@{server_address}:{self.reality_port}?{query_string}#{email}_reality"
            
        else:
            # Create WebSocket + TLS link
            server_address = self.server_domain
            if not server_address:
                return "Error: Domain not configured for WebSocket+TLS"
                
            params = {
                "security": "tls",
                "encryption": "none",
                "type": "ws",
                "path": "/ws"
            }
            
            # Convert params to URL query string
            query_parts = []
            for key, value in params.items():
                query_parts.append(f"{key}={value}")
            
            query_string = "&".join(query_parts)
            
            return f"vless://{uuid}@{server_address}:{self.ws_port}?{query_string}#{email}_websocket"
    
    def reload_xray(self) -> bool:
        """Reload Xray to apply changes"""
        try:
            subprocess.run(["systemctl", "restart", "xray"], check=True)
            logger.info("Xray service restarted successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to restart Xray service: {e}")
            return False
    
    def get_user_traffic(self, email: str) -> Dict[str, int]:
        """
        Get traffic usage for a user
        
        Args:
            email: User email identifier
            
        Returns:
            Dict with uplink and downlink bytes
        """
        try:
            # Call Xray API to get stats
            uplink_cmd = ["xray", "api", "statsquery", "--server=127.0.0.1:10085", f"--pattern=user>>>{email}>>>traffic>>>uplink"]
            downlink_cmd = ["xray", "api", "statsquery", "--server=127.0.0.1:10085", f"--pattern=user>>>{email}>>>traffic>>>downlink"]
            
            uplink_result = subprocess.run(uplink_cmd, capture_output=True, text=True)
            downlink_result = subprocess.run(downlink_cmd, capture_output=True, text=True)
            
            # Parse results
            uplink_bytes = 0
            downlink_bytes = 0
            
            try:
                # Try to extract the value from JSON response
                if uplink_result.stdout:
                    uplink_data = json.loads(uplink_result.stdout)
                    uplink_bytes = uplink_data.get('stat', [{}])[0].get('value', 0)
            except (json.JSONDecodeError, IndexError, KeyError) as e:
                logger.error(f"Error parsing uplink traffic data: {e}")
                
            try:
                # Try to extract the value from JSON response
                if downlink_result.stdout:
                    downlink_data = json.loads(downlink_result.stdout)
                    downlink_bytes = downlink_data.get('stat', [{}])[0].get('value', 0)
            except (json.JSONDecodeError, IndexError, KeyError) as e:
                logger.error(f"Error parsing downlink traffic data: {e}")
                
            return {
                "uplink": int(uplink_bytes),
                "downlink": int(downlink_bytes),
                "total": int(uplink_bytes) + int(downlink_bytes)
            }
            
        except Exception as e:
            logger.error(f"Error getting user traffic: {e}")
            return {"uplink": 0, "downlink": 0, "total": 0}
    
    def reset_user_traffic(self, email: str) -> bool:
        """Reset traffic statistics for a user"""
        try:
            # Reset uplink and downlink stats
            uplink_cmd = ["xray", "api", "statsquery", "--server=127.0.0.1:10085", 
                        f"--pattern=user>>>{email}>>>traffic>>>uplink", "--reset"]
            downlink_cmd = ["xray", "api", "statsquery", "--server=127.0.0.1:10085", 
                          f"--pattern=user>>>{email}>>>traffic>>>downlink", "--reset"]
            
            subprocess.run(uplink_cmd, check=True)
            subprocess.run(downlink_cmd, check=True)
            
            logger.info(f"Traffic statistics reset for user {email}")
            return True
        except Exception as e:
            logger.error(f"Failed to reset traffic for user {email}: {e}")
            return False

# Create a singleton instance
xray_manager = XRayManager() 