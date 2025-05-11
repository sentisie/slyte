import logging
import uuid
import time
import hmac
import hashlib
import base64
import json
import aiohttp
from typing import Dict, Any, Optional, Tuple, List

from utils.config import config

logger = logging.getLogger(__name__)

class PaymentBase:
    """Base class for payment providers"""
    
    def __init__(self):
        self.name = "base"
    
    async def create_invoice(self, amount: float, days: int, description: str, user_id: int) -> Tuple[bool, Dict[str, Any]]:
        """Create payment invoice"""
        raise NotImplementedError("Subclasses must implement create_invoice")
    
    async def check_payment(self, payment_id: str) -> Tuple[bool, str]:
        """
        Check payment status
        
        Returns:
            Tuple[bool, str]: (is_paid, status)
        """
        raise NotImplementedError("Subclasses must implement check_payment")

class CryptoBot(PaymentBase):
    """CryptoBot payment provider integration"""
    
    def __init__(self):
        super().__init__()
        self.name = "cryptobot"
        self.token = config.get_crypto_bot_token()
        self.api_url = "https://pay.crypt.bot/api"
    
    async def create_invoice(self, amount: float, days: int, description: str, user_id: int) -> Tuple[bool, Dict[str, Any]]:
        """
        Create CryptoBot invoice
        
        Args:
            amount: Payment amount
            days: Subscription days
            description: Invoice description
            user_id: Telegram user ID
            
        Returns:
            Tuple[bool, Dict]: Success flag and response data
        """
        if not self.token:
            logger.error("CryptoBot token not configured")
            return False, {"error": "CryptoBot not configured"}
        
        payload = {
            "amount": amount,
            "currency": "USD",
            "description": description,
            "paid_btn_name": "back_to_bot",
            "paid_btn_url": f"https://t.me/{config.get('bot.username')}",
            "allow_comments": False,
            "allow_anonymous": False,
            "expires_in": 3600  # 1 hour expiration
        }
        
        headers = {
            "Crypto-Pay-API-Token": self.token,
            "Content-Type": "application/json"
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(f"{self.api_url}/createInvoice", json=payload, headers=headers) as resp:
                    if resp.status == 200:
                        response = await resp.json()
                        
                        if response.get("ok"):
                            invoice = response.get("result", {})
                            return True, {
                                "provider": "cryptobot",
                                "payment_id": invoice.get("invoice_id"),
                                "amount": amount,
                                "days": days,
                                "url": invoice.get("pay_url"),
                                "expires_at": int(time.time()) + 3600
                            }
                    
                    error_text = await resp.text()
                    logger.error(f"Failed to create CryptoBot invoice: {error_text}")
                    return False, {"error": f"Payment API error: {error_text}"}
                    
        except Exception as e:
            logger.error(f"Error creating CryptoBot invoice: {e}")
            return False, {"error": f"Payment error: {str(e)}"}
    
    async def check_payment(self, payment_id: str) -> Tuple[bool, str]:
        """
        Check CryptoBot payment status
        
        Args:
            payment_id: CryptoBot invoice ID
            
        Returns:
            Tuple[bool, str]: (is_paid, status)
        """
        if not self.token:
            logger.error("CryptoBot token not configured")
            return False, "not_configured"
        
        headers = {
            "Crypto-Pay-API-Token": self.token
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.api_url}/getInvoice?invoice_id={payment_id}", headers=headers) as resp:
                    if resp.status == 200:
                        response = await resp.json()
                        
                        if response.get("ok"):
                            invoice = response.get("result", {})
                            status = invoice.get("status")
                            
                            if status == "paid":
                                return True, "paid"
                            elif status == "expired":
                                return False, "expired"
                            else:
                                return False, "pending"
                    
                    return False, "error"
                    
        except Exception as e:
            logger.error(f"Error checking CryptoBot payment: {e}")
            return False, "error"

class YooMoney(PaymentBase):
    """YooMoney payment provider integration"""
    
    def __init__(self):
        super().__init__()
        self.name = "yoomoney"
        self.token = config.get_yoomoney_token()
        self.api_url = "https://yoomoney.ru/api"
    
    async def create_invoice(self, amount: float, days: int, description: str, user_id: int) -> Tuple[bool, Dict[str, Any]]:
        """
        Create YooMoney invoice
        
        Args:
            amount: Payment amount
            days: Subscription days
            description: Invoice description
            user_id: Telegram user ID
            
        Returns:
            Tuple[bool, Dict]: Success flag and response data
        """
        if not self.token:
            logger.error("YooMoney token not configured")
            return False, {"error": "YooMoney not configured"}
        
        # Generate payment ID
        payment_id = str(uuid.uuid4())
        
        # Create payment form URL
        amount_rub = int(amount * 80)  # Convert USD to RUB (approximate)
        
        url = (
            f"https://yoomoney.ru/quickpay/confirm.xml?"
            f"receiver={self.token}&"
            f"quickpay-form=shop&"
            f"targets={description}&"
            f"paymentType=SB&"
            f"sum={amount_rub}&"
            f"label={payment_id}"
        )
        
        return True, {
            "provider": "yoomoney",
            "payment_id": payment_id,
            "amount": amount,
            "days": days,
            "url": url,
            "expires_at": int(time.time()) + 3600
        }
    
    async def check_payment(self, payment_id: str) -> Tuple[bool, str]:
        """
        Check YooMoney payment status
        
        Note: This is a simplified example. Real implementation would
        require setting up a webhook receiver or regular API polling.
        
        Args:
            payment_id: YooMoney payment label
            
        Returns:
            Tuple[bool, str]: (is_paid, status)
        """
        if not self.token:
            logger.error("YooMoney token not configured")
            return False, "not_configured"
        
        # For this example, we'll assume payment verification happens elsewhere
        # In a real implementation, you would check the payment using the YooMoney API
        # This would require storing payment IDs and checking their status via API or webhooks
        
        return False, "pending"  # Always pending in this simplified example

class TelegramStars(PaymentBase):
    """Telegram Stars payment provider integration"""
    
    def __init__(self):
        super().__init__()
        self.name = "telegram_stars"
        # Токен не нужен, так как мы будем использовать webhook обратного вызова
        self.api_url = "https://t.me/$"  # Заглушка URL, настоящий URL подставляется динамически
    
    async def create_invoice(self, amount: float, days: int, description: str, user_id: int) -> Tuple[bool, Dict[str, Any]]:
        """
        Create Telegram Stars invoice
        
        Args:
            amount: Payment amount in stars (integer)
            days: Subscription days
            description: Invoice description
            user_id: Telegram user ID
            
        Returns:
            Tuple[bool, Dict]: Success flag and response data
        """
        try:
            # Generate payment ID
            payment_id = str(uuid.uuid4())
            
            # Telegram Stars использует URL прямо из бота
            # Реальная оплата происходит через Telegram API
            # Здесь мы просто генерируем идентификатор транзакции
            
            return True, {
                "provider": "telegram_stars",
                "payment_id": payment_id,
                "amount": amount,
                "days": days,
                "amount_stars": int(amount * 10),  # Примерное соотношение 1$ = 10 звезд
                "url": f"stars_payment_{payment_id}",  # Специальный формат, будет обработан в боте
                "expires_at": int(time.time()) + 3600
            }
                
        except Exception as e:
            logger.error(f"Error creating Telegram Stars invoice: {e}")
            return False, {"error": f"Payment error: {str(e)}"}
    
    async def check_payment(self, payment_id: str) -> Tuple[bool, str]:
        """
        Check Telegram Stars payment status
        
        Args:
            payment_id: Telegram Stars payment ID
            
        Returns:
            Tuple[bool, str]: (is_paid, status)
        """
        # Статус оплаты звездами проверяется через веб-хуки Telegram
        # Этот метод не используется для реальной проверки, 
        # вместо этого бот сам уведомляет об успешной оплате
        return False, "pending"

class USDTPayment(PaymentBase):
    """USDT payment provider integration (via CryptoBot)"""
    
    def __init__(self):
        super().__init__()
        self.name = "usdt"
        self.token = config.get_crypto_bot_token()
        self.api_url = "https://pay.crypt.bot/api"
    
    async def create_invoice(self, amount: float, days: int, description: str, user_id: int) -> Tuple[bool, Dict[str, Any]]:
        """
        Create USDT invoice via CryptoBot
        
        Args:
            amount: Payment amount
            days: Subscription days
            description: Invoice description
            user_id: Telegram user ID
            
        Returns:
            Tuple[bool, Dict]: Success flag and response data
        """
        if not self.token:
            logger.error("CryptoBot token not configured")
            return False, {"error": "CryptoBot not configured"}
        
        payload = {
            "asset": "USDT",
            "amount": str(amount),
            "description": description,
            "paid_btn_name": "back_to_bot",
            "paid_btn_url": f"https://t.me/{config.get('bot.username')}",
            "allow_comments": False,
            "allow_anonymous": False,
            "expires_in": 3600  # 1 hour expiration
        }
        
        headers = {
            "Crypto-Pay-API-Token": self.token,
            "Content-Type": "application/json"
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(f"{self.api_url}/createInvoice", json=payload, headers=headers) as resp:
                    if resp.status == 200:
                        response = await resp.json()
                        
                        if response.get("ok"):
                            invoice = response.get("result", {})
                            return True, {
                                "provider": "usdt",
                                "payment_id": invoice.get("invoice_id"),
                                "amount": amount,
                                "days": days,
                                "url": invoice.get("pay_url"),
                                "expires_at": int(time.time()) + 3600
                            }
                    
                    error_text = await resp.text()
                    logger.error(f"Failed to create USDT invoice: {error_text}")
                    return False, {"error": f"Payment API error: {error_text}"}
                    
        except Exception as e:
            logger.error(f"Error creating USDT invoice: {e}")
            return False, {"error": f"Payment error: {str(e)}"}
    
    async def check_payment(self, payment_id: str) -> Tuple[bool, str]:
        """
        Check USDT payment status
        
        Args:
            payment_id: CryptoBot invoice ID
            
        Returns:
            Tuple[bool, str]: (is_paid, status)
        """
        if not self.token:
            logger.error("CryptoBot token not configured")
            return False, "not_configured"
        
        headers = {
            "Crypto-Pay-API-Token": self.token
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.api_url}/getInvoice?invoice_id={payment_id}", headers=headers) as resp:
                    if resp.status == 200:
                        response = await resp.json()
                        
                        if response.get("ok"):
                            invoice = response.get("result", {})
                            status = invoice.get("status")
                            
                            if status == "paid":
                                return True, "paid"
                            elif status == "expired":
                                return False, "expired"
                            else:
                                return False, "pending"
                    
                    return False, "error"
                    
        except Exception as e:
            logger.error(f"Error checking USDT payment: {e}")
            return False, "error"

class PaymentManager:
    """Manager class for payment providers"""
    
    def __init__(self):
        self.providers = {}
        self.enabled = config.is_payment_enabled()
        self._init_providers()
    
    def _init_providers(self):
        """Initialize payment providers based on configuration"""
        if not self.enabled:
            logger.info("Payments are disabled in configuration")
            return
        
        # Add CryptoBot if configured
        if config.get_crypto_bot_token():
            self.providers["cryptobot"] = CryptoBot()
            logger.info("CryptoBot payment provider initialized")
        
        # Add YooMoney if configured
        if config.get_yoomoney_token():
            self.providers["yoomoney"] = YooMoney()
            logger.info("YooMoney payment provider initialized")
        
        # Add TelegramStars 
        self.providers["telegram_stars"] = TelegramStars()
        logger.info("Telegram Stars payment provider initialized")
        
        # Add USDTPayment if configured
        if config.get_crypto_bot_token():
            self.providers["usdt"] = USDTPayment()
            logger.info("USDT payment provider initialized")
        
        if not self.providers:
            logger.warning("No payment providers configured")
    
    def get_available_providers(self) -> List[str]:
        """Get list of available payment provider names"""
        return list(self.providers.keys())
    
    def get_provider(self, name: str) -> Optional[PaymentBase]:
        """Get payment provider by name"""
        return self.providers.get(name)
    
    async def create_invoice(self, provider: str, amount: float, days: int, 
                           description: str, user_id: int) -> Tuple[bool, Dict[str, Any]]:
        """Create invoice using specified provider"""
        if not self.enabled:
            return False, {"error": "Payments are disabled"}
        
        payment_provider = self.get_provider(provider)
        if not payment_provider:
            return False, {"error": f"Provider {provider} not available"}
        
        return await payment_provider.create_invoice(amount, days, description, user_id)
    
    async def check_payment(self, provider: str, payment_id: str) -> Tuple[bool, str]:
        """Check payment status"""
        if not self.enabled:
            return False, "disabled"
        
        payment_provider = self.get_provider(provider)
        if not payment_provider:
            return False, "provider_not_available"
        
        return await payment_provider.check_payment(payment_id)

# Create singleton instance
payment_manager = PaymentManager() 