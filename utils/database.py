import os
import json
import time
import uuid
import logging
from typing import Dict, List, Any, Optional, Tuple

logger = logging.getLogger(__name__)

class Database:
    _instance = None
    
    def __new__(cls, db_path=None):
        if cls._instance is None:
            cls._instance = super(Database, cls).__new__(cls)
            cls._instance._db_path = db_path or os.path.join('data', 'users.db')
            cls._instance._data = {'users': {}, 'payments': {}, 'stats': {}}
            cls._instance._ensure_db_dir()
            cls._instance._load_data()
        return cls._instance
    
    def _ensure_db_dir(self):
        """Ensure the database directory exists"""
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
    
    def _load_data(self):
        """Load data from the database file"""
        if os.path.exists(self._db_path):
            try:
                with open(self._db_path, 'r') as f:
                    self._data = json.load(f)
                logger.info(f"Database loaded from {self._db_path}")
            except Exception as e:
                logger.error(f"Error loading database: {e}")
                # Keep using the default empty database
        else:
            logger.info(f"Database file not found. Creating new database at {self._db_path}")
            self._save_data()
    
    def _save_data(self):
        """Save data to the database file"""
        try:
            with open(self._db_path, 'w') as f:
                json.dump(self._data, f, indent=2)
            logger.info(f"Database saved to {self._db_path}")
        except Exception as e:
            logger.error(f"Error saving database: {e}")
    
    # User management
    def add_user(self, user_id: int, username: str = None, first_name: str = None,
                last_name: str = None) -> Dict[str, Any]:
        """Add a new user or update existing user"""
        if str(user_id) not in self._data['users']:
            self._data['users'][str(user_id)] = {
                'id': user_id,
                'username': username,
                'first_name': first_name,
                'last_name': last_name,
                'created_at': int(time.time()),
                'subscriptions': [],
                'active_ips': [],
                'is_banned': False
            }
        else:
            # Update user data
            user = self._data['users'][str(user_id)]
            if username:
                user['username'] = username
            if first_name:
                user['first_name'] = first_name
            if last_name:
                user['last_name'] = last_name
        
        self._save_data()
        return self._data['users'][str(user_id)]
    
    def get_user(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Get user data by ID"""
        return self._data['users'].get(str(user_id))
    
    def get_all_users(self) -> List[Dict[str, Any]]:
        """Get all users"""
        return list(self._data['users'].values())
    
    def ban_user(self, user_id: int, ban: bool = True) -> bool:
        """Ban or unban a user"""
        if str(user_id) in self._data['users']:
            self._data['users'][str(user_id)]['is_banned'] = ban
            self._save_data()
            return True
        return False
    
    # Subscription management
    def add_subscription(self, user_id: int, days: int, 
                        payment_id: str = None, server_id: str = None) -> Optional[Dict[str, Any]]:
        """Add a subscription for the user"""
        user = self.get_user(user_id)
        if not user:
            return None
        
        # Generate unique config ID
        config_id = str(uuid.uuid4())
        
        # Create subscription
        now = int(time.time())
        subscription = {
            'id': config_id,
            'user_id': user_id,
            'created_at': now,
            'expires_at': now + (days * 86400),  # days to seconds
            'payment_id': payment_id,
            'is_active': True,
            'server_id': server_id,  # Добавляем ID сервера
            'data': {
                'vless_id': str(uuid.uuid4()),
                'last_reset': now,
                'traffic_used': 0
            }
        }
        
        user['subscriptions'].append(subscription)
        self._save_data()
        return subscription
    
    def extend_subscription(self, user_id: int, subscription_id: str, 
                          days: int) -> Optional[Dict[str, Any]]:
        """Extend an existing subscription"""
        user = self.get_user(user_id)
        if not user:
            return None
        
        for sub in user['subscriptions']:
            if sub['id'] == subscription_id:
                # Extend expiration date
                if sub['expires_at'] < time.time():
                    # If expired, start from now
                    sub['expires_at'] = time.time() + (days * 86400)
                else:
                    # If not expired, add to current expiration
                    sub['expires_at'] += days * 86400
                
                sub['is_active'] = True
                self._save_data()
                return sub
        
        return None
    
    def get_user_subscriptions(self, user_id: int) -> List[Dict[str, Any]]:
        """Get all subscriptions for a user"""
        user = self.get_user(user_id)
        if not user:
            return []
        
        return user['subscriptions']
    
    def get_active_subscriptions(self, user_id: int, server_id: str = None) -> List[Dict[str, Any]]:
        """
        Get active subscriptions for a user, optionally filtered by server ID
        """
        all_subs = self.get_user_subscriptions(user_id)
        now = time.time()
        
        if server_id:
            # Filter by server ID and active state
            return [
                sub for sub in all_subs if 
                sub['is_active'] and sub['expires_at'] > now and 
                sub.get('server_id') == server_id
            ]
        else:
            # Filter only by active state
            return [sub for sub in all_subs if sub['is_active'] and sub['expires_at'] > now]
    
    def deactivate_subscription(self, user_id: int, subscription_id: str) -> bool:
        """Deactivate a subscription"""
        user = self.get_user(user_id)
        if not user:
            return False
        
        for sub in user['subscriptions']:
            if sub['id'] == subscription_id:
                sub['is_active'] = False
                self._save_data()
                return True
        
        return False
    
    # Payment tracking
    def record_payment(self, user_id: int, payment_id: str, amount: float, 
                     currency: str, status: str = 'pending',
                     subscription_days: int = None, server_id: str = None) -> Dict[str, Any]:
        """Record a payment with optional server ID"""
        if payment_id not in self._data['payments']:
            payment = {
                'id': payment_id,
                'user_id': user_id,
                'amount': amount,
                'currency': currency,
                'status': status,
                'server_id': server_id,  # Добавляем ID сервера
                'created_at': int(time.time()),
                'updated_at': int(time.time()),
                'subscription_days': subscription_days
            }
            self._data['payments'][payment_id] = payment
            self._save_data()
            return payment
        
        return self._data['payments'][payment_id]
    
    def update_payment_status(self, payment_id: str, status: str) -> Optional[Dict[str, Any]]:
        """Update the status of a payment"""
        if payment_id in self._data['payments']:
            payment = self._data['payments'][payment_id]
            payment['status'] = status
            payment['updated_at'] = int(time.time())
            self._save_data()
            return payment
        
        return None
    
    def get_payment(self, payment_id: str) -> Optional[Dict[str, Any]]:
        """Get payment by ID"""
        return self._data['payments'].get(payment_id)
    
    def get_user_payments(self, user_id: int) -> List[Dict[str, Any]]:
        """Get all payments for a user"""
        return [p for p in self._data['payments'].values() if p['user_id'] == user_id]
    
    # Traffic tracking
    def update_traffic(self, subscription_id: str, bytes_used: int) -> bool:
        """Update traffic usage for a subscription"""
        for user_id, user in self._data['users'].items():
            for sub in user['subscriptions']:
                if sub['id'] == subscription_id:
                    sub['data']['traffic_used'] += bytes_used
                    self._save_data()
                    return True
        
        return False
    
    def reset_traffic(self, subscription_id: str) -> bool:
        """Reset traffic counter for a subscription"""
        for user_id, user in self._data['users'].items():
            for sub in user['subscriptions']:
                if sub['id'] == subscription_id:
                    sub['data']['traffic_used'] = 0
                    sub['data']['last_reset'] = int(time.time())
                    self._save_data()
                    return True
        
        return False
    
    # IP tracking
    def add_ip_to_user(self, user_id: int, ip: str) -> Tuple[bool, List[str]]:
        """Add an IP to user's active IPs, return success and list of IPs"""
        user = self.get_user(user_id)
        if not user:
            return False, []
        
        if ip not in user['active_ips']:
            user['active_ips'].append(ip)
            self._save_data()
        
        return True, user['active_ips']
    
    def remove_ip_from_user(self, user_id: int, ip: str) -> bool:
        """Remove an IP from user's active IPs"""
        user = self.get_user(user_id)
        if not user or ip not in user['active_ips']:
            return False
        
        user['active_ips'].remove(ip)
        self._save_data()
        return True
    
    def clear_user_ips(self, user_id: int) -> bool:
        """Clear all active IPs for a user"""
        user = self.get_user(user_id)
        if not user:
            return False
        
        user['active_ips'] = []
        self._save_data()
        return True

# Create a singleton instance
database = Database() 