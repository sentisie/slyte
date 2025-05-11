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
    def __init__(self):
        self.config_path = config.get('xray.config_path', '/etc/xray/config.json')
        self.server_ip = config.get('server.ip')
        self.server_domain = config.get('server.domain')
        self.reality_port = config.get('server.reality_port', 443)
        self.ws_port = config.get('server.vless_port', 443)
        self.reality_settings = config.get('xray.reality', {})
        
        # Автоматическая генерация ключей, если включено
        if config.is_auto_generate_keys_enabled():
            self._init_reality_keys()
    
    def _init_reality_keys(self):
        """Initialize Reality keys if they are not set or auto-generation is enabled"""
        # Проверяем, есть ли уже ключи
        private_key = self.reality_settings.get('private_key', '')
        
        if not private_key or private_key == 'your_private_key_here':
            logger.info("Auto-generating Reality keys...")
            
            # Генерируем новую пару ключей
            private_key, public_key = self.generate_keys()
            
            if private_key and public_key:
                # Генерируем short_id
                short_id = os.urandom(4).hex()
                
                # Обновляем настройки в памяти
                self.reality_settings['private_key'] = private_key
                self.reality_settings['public_key'] = public_key
                self.reality_settings['short_id'] = short_id
                
                logger.info("Reality keys generated successfully")
                logger.info(f"Private Key: {private_key}")
                logger.info(f"Public Key: {public_key}")
                logger.info(f"Short ID: {short_id}")
            else:
                logger.error("Failed to generate Reality keys")
    
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
        inbound_tag = "vless-reality" if protocol == "reality" else "vless-ws"
        for inbound in config_data["inbounds"]:
            if inbound.get("tag") == inbound_tag:
                # Add the user to the inbound
                inbound["settings"]["clients"].append(user)
                break
        
        # Save the updated configuration
        self.save_config(config_data)
        
        # Reload Xray to apply changes
        self.reload_xray()
        
        return user
    
    def remove_user(self, email: str) -> bool:
        """Remove a user from Xray configuration"""
        config_data = self.load_config()
        found = False
        
        # Find and remove the user from all inbounds
        for inbound in config_data["inbounds"]:
            if "settings" in inbound and "clients" in inbound["settings"]:
                clients = inbound["settings"]["clients"]
                new_clients = [c for c in clients if c.get("email") != email]
                
                if len(new_clients) != len(clients):
                    inbound["settings"]["clients"] = new_clients
                    found = True
        
        if found:
            # Save the updated configuration
            self.save_config(config_data)
            
            # Reload Xray to apply changes
            self.reload_xray()
            
        return found
    
    def get_user(self, email: str) -> Optional[Dict[str, Any]]:
        """Get user configuration by email"""
        config_data = self.load_config()
        
        for inbound in config_data["inbounds"]:
            if "settings" in inbound and "clients" in inbound["settings"]:
                for client in inbound["settings"]["clients"]:
                    if client.get("email") == email:
                        return {
                            "uuid": client.get("id"),
                            "email": client.get("email"),
                            "protocol": "reality" if inbound.get("tag") == "vless-reality" else "websocket",
                            "inbound": inbound.get("tag")
                        }
        
        return None
    
    def get_all_users(self) -> List[Dict[str, Any]]:
        """Get all users from Xray configuration"""
        config_data = self.load_config()
        users = []
        
        for inbound in config_data["inbounds"]:
            if "settings" in inbound and "clients" in inbound["settings"]:
                for client in inbound["settings"]["clients"]:
                    users.append({
                        "uuid": client.get("id"),
                        "email": client.get("email"),
                        "protocol": "reality" if inbound.get("tag") == "vless-reality" else "websocket",
                        "inbound": inbound.get("tag")
                    })
        
        return users
    
    def generate_vless_link(self, uuid: str, email: str, protocol: str = "reality") -> str:
        """Generate a VLESS connection link"""
        if protocol == "reality":
            # Reality link format
            server_name = self.reality_settings.get('server_names', ["www.microsoft.com"])[0]
            public_key = self.reality_settings.get('public_key', '')
            short_id = self.reality_settings.get('short_id', '')
            
            link = (
                f"vless://{uuid}@{self.server_domain or self.server_ip}:{self.reality_port}"
                f"?security=reality"
                f"&sni={server_name}"
                f"&fp=chrome"
                f"&pbk={public_key}"
                f"&sid={short_id}"
                f"&type=tcp"
                f"&flow=xtls-rprx-vision"
                f"#{email}"
            )
        else:
            # WebSocket link format
            link = (
                f"vless://{uuid}@{self.server_domain or self.server_ip}:{self.ws_port}"
                f"?type=ws"
                f"&security=tls"
                f"&path=%2Fws"
                f"&host={self.server_domain}"
                f"&sni={self.server_domain}"
                f"#{email}"
            )
        
        return link
    
    def reload_xray(self) -> bool:
        """Reload Xray service to apply configuration changes"""
        try:
            subprocess.run(["systemctl", "restart", "xray"], check=True)
            logger.info("Xray service restarted successfully")
            return True
        except subprocess.SubprocessError as e:
            logger.error(f"Failed to restart Xray service: {e}")
            return False
    
    def get_user_traffic(self, email: str) -> Dict[str, int]:
        """Get traffic statistics for a specific user"""
        try:
            # Get download stats
            download_cmd = f"xray api stats --server=127.0.0.1:10085 -name 'user>>>{email}>>>traffic>>>downlink'"
            download_result = subprocess.run(
                download_cmd,
                shell=True,
                capture_output=True,
                text=True
            )
            
            # Get upload stats
            upload_cmd = f"xray api stats --server=127.0.0.1:10085 -name 'user>>>{email}>>>traffic>>>uplink'"
            upload_result = subprocess.run(
                upload_cmd,
                shell=True,
                capture_output=True,
                text=True
            )
            
            # Parse results
            try:
                download = int(json.loads(download_result.stdout)["stat"]["value"])
            except:
                download = 0
                
            try:
                upload = int(json.loads(upload_result.stdout)["stat"]["value"])
            except:
                upload = 0
            
            return {
                "download": download,
                "upload": upload,
                "total": download + upload
            }
            
        except Exception as e:
            logger.error(f"Error getting traffic stats for {email}: {e}")
            return {
                "download": 0,
                "upload": 0, 
                "total": 0
            }
    
    def reset_user_traffic(self, email: str) -> bool:
        """Reset traffic statistics for a specific user"""
        try:
            # Reset download stats
            download_cmd = f"xray api stats --server=127.0.0.1:10085 -name 'user>>>{email}>>>traffic>>>downlink' -reset"
            subprocess.run(download_cmd, shell=True, check=True)
            
            # Reset upload stats
            upload_cmd = f"xray api stats --server=127.0.0.1:10085 -name 'user>>>{email}>>>traffic>>>uplink' -reset"
            subprocess.run(upload_cmd, shell=True, check=True)
            
            logger.info(f"Traffic stats reset for user {email}")
            return True
            
        except Exception as e:
            logger.error(f"Error resetting traffic stats for {email}: {e}")
            return False

# Create singleton instance
xray_manager = XRayManager() 