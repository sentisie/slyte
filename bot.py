#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import logging
import asyncio
from datetime import datetime, timedelta
import uuid
import io

from telegram import (
    Update, 
    InlineKeyboardButton, 
    InlineKeyboardMarkup,
    InputFile
)

from telegram.ext import (
    Application, 
    CommandHandler, 
    CallbackContext,
    CallbackQueryHandler,
    MessageHandler, 
    filters, 
    ContextTypes
)

from utils import logger, config, database, xray_manager, payment_manager
from utils.qrcode_generator import generate_vless_qr

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Константы для состояний в рамках разговора
AWAITING_PAYMENT = 'AWAITING_PAYMENT'
CHECKING_PAYMENT = 'CHECKING_PAYMENT'
AWAITING_PROTOCOL = 'AWAITING_PROTOCOL'

# Функции для форматирования
def format_bytes(size):
    """Преобразование размера в человекочитаемый формат"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0:
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} PB"

def format_time_left(seconds):
    """Преобразование оставшегося времени в читаемый формат"""
    if seconds < 0:
        return "Истекло"
    
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    
    parts = []
    if days > 0:
        parts.append(f"{int(days)} д.")
    if hours > 0:
        parts.append(f"{int(hours)} ч.")
    if minutes > 0 and days == 0:  # Показываем минуты только если осталось меньше дня
        parts.append(f"{int(minutes)} мин.")
    
    return " ".join(parts) or "Меньше минуты"

# Проверка прав администратора
def is_admin(user_id):
    """Проверяет, является ли пользователь администратором"""
    admin_ids = config.get_admin_ids()
    return user_id in admin_ids

# Получение доступных тарифных планов
def get_subscription_plans():
    """Получает список тарифных планов из конфигурации"""
    return config.get_subscription_plans()

# Основные обработчики команд
async def start_command(update: Update, context: CallbackContext):
    """Обработчик команды /start"""
    user = update.effective_user
    
    # Регистрируем или обновляем данные пользователя
    database.add_user(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name
    )
    
    # Сообщение приветствия
    await update.message.reply_text(
        f"👋 Здравствуйте, {user.first_name}!\n\n"
        f"Я бот для предоставления VLESS VPN доступа.\n"
        f"Используйте меню для покупки подписки и управления вашим аккаунтом."
    )
    
    # Показываем основное меню
    await show_main_menu(update, context)

async def activate_trial(update: Update, context: CallbackContext):
    """Активация пробного периода"""
    query = update.callback_query
    user_id = update.effective_user.id
    
    # Проверяем, включен ли пробный период
    if not config.is_trial_enabled():
        await query.answer("Пробный период временно недоступен")
        return
    
    # Проверяем, есть ли уже активные подписки
    active_subs = database.get_active_subscriptions(user_id)
    if active_subs:
        await query.answer("У вас уже есть активная подписка")
        return
    
    # Проверяем, использовал ли пользователь пробный период ранее
    user = database.get_user(user_id)
    all_subs = database.get_user_subscriptions(user_id)
    
    trial_used = any(sub.get('is_trial', False) for sub in all_subs)
    if trial_used:
        await query.answer("Вы уже использовали пробный период")
        return
    
    # Создаем пробную подписку
    trial_days = config.get_trial_days()
    subscription = database.add_subscription(
        user_id=user_id,
        days=trial_days,
        payment_id=None  # Без платежа
    )
    
    if subscription:
        # Отмечаем подписку как пробную
        subscription['is_trial'] = True
        
        # Создаем пользователя в Xray
        email = f"trial_user_{user_id}_{subscription['id']}"
        xray_user = xray_manager.add_user(email)
        
        # Добавляем UUID в данные подписки
        subscription['data']['vless_id'] = xray_user['id']
        
        # Обновляем информацию пользователя
        await query.edit_message_text(
            f"✅ *Поздравляем!*\n\n"
            f"Ваш пробный период на {trial_days} дней активирован.\n"
            f"Теперь вы можете получить конфигурацию для подключения.",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔑 Моя подписка", callback_data="my_subscription")
            ]])
        )
    else:
        await query.answer("Произошла ошибка при активации пробного периода")

async def help_command(update: Update, context: CallbackContext):
    """Обработчик команды /help"""
    help_text = (
        "🔹 *Основные команды:*\n"
        "/start - Запустить бота\n"
        "/help - Получить справку\n"
        "/subscription - Управление подпиской\n"
        "/prices - Тарифные планы\n\n"
        
        "🔹 *Дополнительно:*\n"
        "/qr - Получить QR-код конфигурации\n"
        "/traffic - Проверить использование трафика\n"
        "/support - Связаться с поддержкой\n\n"
        
        "🔹 *Для админов:*\n"
        "/admin - Панель администратора\n"
        "/stats - Статистика использования\n"
        "/users - Управление пользователями"
    )
    
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def show_main_menu(update: Update, context: CallbackContext):
    """Показывает основное меню с кнопками"""
    user_id = update.effective_user.id
    user_data = database.get_user(user_id)
    
    # Проверяем, есть ли у пользователя активная подписка
    active_subs = database.get_active_subscriptions(user_id)
    
    keyboard = [
        [InlineKeyboardButton("💰 Тарифы и оплата", callback_data="prices")]
    ]
    
    if active_subs:
        # У пользователя есть активная подписка
        keyboard.append([InlineKeyboardButton("🔑 Моя подписка", callback_data="my_subscription")])
        keyboard.append([InlineKeyboardButton("📊 Статистика трафика", callback_data="traffic")])
        keyboard.append([InlineKeyboardButton("📱 Получить QR-код", callback_data="qr_code")])
    else:
        # У пользователя нет активной подписки
        keyboard.append([InlineKeyboardButton("🔑 Купить подписку", callback_data="buy_subscription")])
        
        # Проверяем, использовал ли пользователь пробный период и доступен ли он
        if config.is_trial_enabled():
            all_subs = database.get_user_subscriptions(user_id)
            trial_used = any(sub.get('is_trial', False) for sub in all_subs)
            
            if not trial_used:
                keyboard.append([InlineKeyboardButton("🎁 Активировать пробный период", callback_data="activate_trial")])
    
    # Кнопка поддержки
    keyboard.append([InlineKeyboardButton("🆘 Поддержка", callback_data="support")])
    
    # Добавляем кнопку администратора для админов
    if is_admin(user_id):
        keyboard.append([InlineKeyboardButton("⚙️ Админ-панель", callback_data="admin")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Определяем заголовок сообщения в зависимости от наличия подписки
    if active_subs:
        sub = active_subs[0]  # Берем первую активную подписку
        expiry_date = datetime.fromtimestamp(sub['expires_at'])
        time_left = sub['expires_at'] - time.time()
        
        title = (
            f"🔹 *Ваша подписка активна*\n\n"
            f"⏳ Осталось: {format_time_left(time_left)}\n"
            f"📅 Истекает: {expiry_date.strftime('%d.%m.%Y')}\n"
            f"📲 Выберите действие из меню ниже:"
        )
    else:
        title = (
            f"🔹 *Главное меню*\n\n"
            f"У вас нет активной подписки.\n"
            f"Выберите 'Купить подписку' для продолжения."
        )
    
    # Отправляем сообщение или редактируем существующее
    if update.callback_query:
        await update.callback_query.edit_message_text(
            text=title,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            text=title,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )

# Обработчики для покупки и управления подпиской
async def show_prices(update: Update, context: CallbackContext):
    """Показывает доступные тарифные планы"""
    plans = get_subscription_plans()
    
    if not plans:
        await update.callback_query.answer("Тарифные планы временно недоступны")
        return
    
    # Создаем текст с описанием планов
    text = "🔹 *Доступные тарифные планы:*\n\n"
    
    for idx, plan in enumerate(plans, 1):
        stars_price = plan.get('price_stars', int(plan['price'] * 10))
        text += (
            f"{idx}. *{plan['title']}*\n"
            f"   ⏳ Срок: {plan['days']} дней\n"
            f"   💲 Цена: ${plan['price']} (USDT)\n"
            f"   ⭐ Звезды: {stars_price} звезд\n\n"
        )
    
    text += "Выберите тарифный план для продолжения:"
    
    # Создаем кнопки для выбора плана
    keyboard = []
    for idx, plan in enumerate(plans, 1):
        keyboard.append([
            InlineKeyboardButton(
                f"{plan['title']} - ${plan['price']}",
                callback_data=f"select_plan_{idx-1}"
            )
        ])
    
    # Проверяем, доступен ли пробный период
    if config.is_trial_enabled():
        trial_days = config.get_trial_days()
        # Проверяем, использовал ли пользователь пробный период
        user_id = update.effective_user.id
        all_subs = database.get_user_subscriptions(user_id)
        trial_used = any(sub.get('is_trial', False) for sub in all_subs)
        
        if not trial_used:
            keyboard.append([
                InlineKeyboardButton(
                    f"🎁 Бесплатный пробный период ({trial_days} дня)",
                    callback_data="activate_trial"
                )
            ])
    
    # Добавляем кнопку возврата
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="back_to_main")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Отвечаем на запрос
    await update.callback_query.edit_message_text(
        text=text,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def select_plan(update: Update, context: CallbackContext):
    """Обработчик выбора тарифного плана"""
    query = update.callback_query
    
    # Получаем индекс выбранного плана
    plan_idx = int(query.data.split('_')[-1])
    plans = get_subscription_plans()
    
    if plan_idx < 0 or plan_idx >= len(plans):
        await query.answer("Выбран неверный тарифный план")
        return
    
    # Выбранный план
    plan = plans[plan_idx]
    
    # Сохраняем выбранный план в контексте
    context.user_data['selected_plan'] = plan
    
    # Показываем опции оплаты
    await show_payment_options(update, context, plan)

async def show_payment_options(update: Update, context: CallbackContext, plan=None):
    """Показывает доступные методы оплаты"""
    query = update.callback_query
    
    # Получаем план, если не был передан
    if not plan:
        plan = context.user_data.get('selected_plan')
    
    if not plan:
        await query.answer("Выберите тарифный план сначала")
        await show_prices(update, context)
        return
    
    # Получаем доступные платежные системы
    payment_providers = payment_manager.get_available_providers()
    
    if not payment_providers:
        await query.edit_message_text(
            "К сожалению, платежные системы временно недоступны. Попробуйте позже или свяжитесь с поддержкой.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ Назад", callback_data="prices")
            ]])
        )
        return
    
    # Создаем текст
    text = (
        f"🔹 *Оплата подписки*\n\n"
        f"Тарифный план: *{plan['title']}*\n"
        f"Срок: {plan['days']} дней\n\n"
        f"Стоимость:\n"
        f"💲 ${plan['price']} (USDT)\n"
        f"⭐ {plan.get('price_stars', int(plan['price']*10))} звезд Telegram\n\n"
        f"Выберите способ оплаты:"
    )
    
    # Создаем кнопки для выбора способа оплаты
    keyboard = []
    
    if "usdt" in payment_providers:
        keyboard.append([
            InlineKeyboardButton("💲 Оплатить USDT", callback_data="pay_usdt")
        ])
    
    if "telegram_stars" in payment_providers:
        keyboard.append([
            InlineKeyboardButton("⭐ Оплатить звездами Telegram", callback_data="pay_telegram_stars")
        ])
    
    if "cryptobot" in payment_providers:
        keyboard.append([
            InlineKeyboardButton("💳 CryptoBot (BTC, ETH, TON)", callback_data="pay_cryptobot")
        ])
    
    if "yoomoney" in payment_providers:
        keyboard.append([
            InlineKeyboardButton("💳 YooMoney", callback_data="pay_yoomoney")
        ])
    
    # Добавляем кнопку возврата
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="prices")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Отвечаем на запрос
    await query.edit_message_text(
        text=text,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def process_payment(update: Update, context: CallbackContext):
    """Обрабатывает запрос на оплату выбранным методом"""
    query = update.callback_query
    user_id = update.effective_user.id
    
    # Получаем метод оплаты
    payment_method = query.data.split('_')[1]
    
    # Особая обработка для Telegram Stars
    if payment_method == "telegram_stars":
        # Получаем выбранный план
        plan = context.user_data.get('selected_plan')
        if not plan:
            await query.answer("Выберите тарифный план сначала")
            await show_prices(update, context)
            return
        
        # Для Telegram Stars мы создаем специальный URL, который будет обработан в самом боте
        stars_amount = plan.get('price_stars', int(plan['price'] * 10))
        
        # Создаем уникальный ID платежа
        payment_id = str(uuid.uuid4())
        
        # Записываем платеж в базу данных
        database.record_payment(
            user_id=user_id,
            payment_id=payment_id,
            amount=plan['price'],
            currency="STARS",
            status="pending",
            subscription_days=plan['days']
        )
        
        # Создаем инструкцию для оплаты звездами
        text = (
            f"🔹 *Оплата звездами Telegram*\n\n"
            f"Для оплаты подписки отправьте *{stars_amount} звезд* боту.\n\n"
            f"1️⃣ Нажмите на иконку ⭐ внизу окна чата\n"
            f"2️⃣ Укажите количество звезд: {stars_amount}\n"
            f"3️⃣ Подтвердите отправку\n\n"
            f"После получения звезд, ваша подписка будет активирована автоматически."
        )
        
        # Создаем кнопки
        keyboard = [
            [InlineKeyboardButton("◀️ Назад", callback_data="prices")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Отвечаем на запрос
        await query.edit_message_text(
            text=text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
        return
    
    # Получаем выбранный план
    plan = context.user_data.get('selected_plan')
    if not plan:
        await query.answer("Выберите тарифный план сначала")
        await show_prices(update, context)
        return
    
    # Создаем описание платежа
    description = f"VPN подписка ({plan['title']}) - {plan['days']} дней"
    
    # Создаем счет через менеджер платежей
    success, result = await payment_manager.create_invoice(
        provider=payment_method,
        amount=plan['price'],
        days=plan['days'],
        description=description,
        user_id=user_id
    )
    
    if not success:
        error_msg = result.get('error', 'Неизвестная ошибка')
        await query.edit_message_text(
            f"❌ Ошибка создания счета: {error_msg}\n\nПопробуйте другой метод оплаты или свяжитесь с поддержкой.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ Назад", callback_data="prices")
            ]])
        )
        return
    
    # Сохраняем информацию о платеже
    payment_id = result.get('payment_id')
    payment_url = result.get('url')
    expires_at = result.get('expires_at')
    
    # Записываем платеж в базу данных
    database.record_payment(
        user_id=user_id,
        payment_id=payment_id,
        amount=plan['price'],
        currency="USD",
        status="pending",
        subscription_days=plan['days']
    )
    
    # Сохраняем данные платежа в контексте
    context.user_data['payment_data'] = {
        'payment_id': payment_id,
        'provider': payment_method,
        'expires_at': expires_at,
        'plan': plan
    }
    
    # Формируем сообщение
    text = (
        f"🔹 *Счет для оплаты создан*\n\n"
        f"Тарифный план: *{plan['title']}*\n"
        f"Срок: {plan['days']} дней\n"
        f"Сумма к оплате: *${plan['price']}*\n\n"
        f"⏳ Счет действителен до: {datetime.fromtimestamp(expires_at).strftime('%d.%m.%Y %H:%M')}\n\n"
        f"Для оплаты нажмите кнопку 'Оплатить' ниже. После оплаты нажмите 'Проверить оплату'."
    )
    
    # Создаем кнопки
    keyboard = [
        [InlineKeyboardButton("💰 Оплатить", url=payment_url)],
        [InlineKeyboardButton("🔄 Проверить оплату", callback_data=f"check_payment_{payment_id}")],
        [InlineKeyboardButton("◀️ Назад", callback_data="prices")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Отвечаем на запрос
    await query.edit_message_text(
        text=text,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    
    # Создаем задачу для периодической проверки платежа
    context.job_queue.run_repeating(
        check_payment_job,
        interval=30,  # Проверяем каждые 30 секунд
        first=10,     # Первая проверка через 10 секунд
        data={
            'user_id': user_id,
            'payment_id': payment_id,
            'provider': payment_method,
            'chat_id': update.effective_chat.id,
            'message_id': query.message.message_id
        },
        name=f"payment_{payment_id}"
    )

async def check_payment_manually(update: Update, context: CallbackContext):
    """Ручная проверка статуса платежа по запросу пользователя"""
    query = update.callback_query
    user_id = update.effective_user.id
    
    # Получаем ID платежа
    payment_id = query.data.split('_')[-1]
    
    # Получаем информацию о платеже из базы данных
    payment_info = database.get_payment(payment_id)
    
    if not payment_info:
        await query.answer("Платеж не найден", show_alert=True)
        return
    
    # Проверяем, принадлежит ли платеж этому пользователю
    if payment_info['user_id'] != user_id:
        await query.answer("Платеж не найден", show_alert=True)
        return
    
    # Если платеж уже отмечен как оплаченный
    if payment_info['status'] == 'paid':
        await query.answer("Платеж уже был обработан", show_alert=True)
        await show_main_menu(update, context)
        return
    
    # Проверяем статус платежа
    provider = payment_info.get('provider', 'cryptobot')  # По умолчанию cryptobot
    is_paid, status = await payment_manager.check_payment(provider, payment_id)
    
    if is_paid:
        # Платеж успешен, обновляем статус и создаем подписку
        database.update_payment_status(payment_id, 'paid')
        
        # Создаем подписку
        days = payment_info.get('subscription_days', 30)  # По умолчанию 30 дней
        subscription = database.add_subscription(user_id, days, payment_id)
        
        if subscription:
            # Создаем пользователя в Xray
            email = f"user_{user_id}_{subscription['id']}"
            xray_user = xray_manager.add_user(email)
            
            # Добавляем UUID в данные подписки
            subscription['data']['vless_id'] = xray_user['id']
            
            # Показываем сообщение об успешной оплате
            await query.edit_message_text(
                "✅ *Оплата успешно получена!*\n\n"
                "Ваша подписка активирована. Сейчас вы будете перенаправлены в меню управления подпиской.",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔑 Моя подписка", callback_data="my_subscription")
                ]])
            )
            
            # Останавливаем задачу проверки платежа
            for job in context.job_queue.get_jobs_by_name(f"payment_{payment_id}"):
                job.schedule_removal()
                
            return
    elif status == "expired":
        # Платеж просрочен
        database.update_payment_status(payment_id, 'expired')
        
        await query.edit_message_text(
            "❌ *Срок действия счета истек*\n\n"
            "Пожалуйста, создайте новый счет для оплаты.",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔄 Создать новый счет", callback_data="prices")
            ]])
        )
        
        # Останавливаем задачу проверки платежа
        for job in context.job_queue.get_jobs_by_name(f"payment_{payment_id}"):
            job.schedule_removal()
    else:
        # Платеж в процессе или ошибка
        await query.answer(
            "Оплата еще не поступила. Пожалуйста, завершите оплату или подождите несколько минут.",
            show_alert=True
        )

async def check_payment_job(context: CallbackContext):
    """Автоматическая периодическая проверка платежа"""
    job_data = context.job.data
    
    user_id = job_data.get('user_id')
    payment_id = job_data.get('payment_id')
    provider = job_data.get('provider')
    chat_id = job_data.get('chat_id')
    message_id = job_data.get('message_id')
    
    # Получаем информацию о платеже из базы данных
    payment_info = database.get_payment(payment_id)
    
    if not payment_info or payment_info['status'] in ['paid', 'expired']:
        # Останавливаем проверку, если платеж уже обработан или не найден
        context.job.schedule_removal()
        return
    
    # Проверяем статус платежа
    is_paid, status = await payment_manager.check_payment(provider, payment_id)
    
    if is_paid:
        # Платеж успешен, обновляем статус и создаем подписку
        database.update_payment_status(payment_id, 'paid')
        
        # Создаем подписку
        days = payment_info.get('subscription_days', 30)
        subscription = database.add_subscription(user_id, days, payment_id)
        
        if subscription:
            # Создаем пользователя в Xray
            email = f"user_{user_id}_{subscription['id']}"
            xray_user = xray_manager.add_user(email)
            
            # Добавляем UUID в данные подписки
            subscription['data']['vless_id'] = xray_user['id']
            
            # Отправляем сообщение пользователю
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=(
                    "✅ *Оплата успешно получена!*\n\n"
                    "Ваша подписка активирована. Перейдите в меню управления подпиской."
                ),
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔑 Моя подписка", callback_data="my_subscription")
                ]])
            )
            
            context.job.schedule_removal()
        
    elif status == "expired":
        # Платеж просрочен
        database.update_payment_status(payment_id, 'expired')
        
        # Отправляем сообщение пользователю
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=(
                "❌ *Срок действия счета истек*\n\n"
                "Пожалуйста, создайте новый счет для оплаты."
            ),
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔄 Создать новый счет", callback_data="prices")
            ]])
        )
        
        context.job.schedule_removal() 

# Обработчики для управления подпиской
async def show_subscription(update: Update, context: CallbackContext):
    """Показывает информацию о подписке пользователя"""
    query = update.callback_query
    user_id = update.effective_user.id
    
    # Получаем активные подписки
    active_subs = database.get_active_subscriptions(user_id)
    
    if not active_subs:
        # Нет активных подписок
        await query.edit_message_text(
            "У вас нет активных подписок. Выберите тарифный план для покупки.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("💰 Тарифы и оплата", callback_data="prices"),
                InlineKeyboardButton("◀️ Назад", callback_data="back_to_main")
            ]])
        )
        return
    
    # Берем первую активную подписку
    sub = active_subs[0]
    
    # Получаем VLESS-ID
    vless_id = sub['data'].get('vless_id', '❌ Неизвестно')
    
    # Получаем статистику трафика
    email = f"user_{user_id}_{sub['id']}"
    traffic_stats = xray_manager.get_user_traffic(email)
    
    # Формируем информацию о подписке
    expiry_date = datetime.fromtimestamp(sub['expires_at'])
    time_left = sub['expires_at'] - time.time()
    created_date = datetime.fromtimestamp(sub['created_at'])
    
    # Генерируем VLESS-ссылку
    vless_link = xray_manager.generate_vless_link(vless_id, email)
    
    text = (
        f"🔹 *Информация о подписке*\n\n"
        f"📅 Дата создания: {created_date.strftime('%d.%m.%Y')}\n"
        f"⏳ Действует до: {expiry_date.strftime('%d.%m.%Y')} ({format_time_left(time_left)})\n\n"
        f"📊 Использовано трафика:\n"
        f"  ⬇️ Скачано: {format_bytes(traffic_stats['download'])}\n"
        f"  ⬆️ Загружено: {format_bytes(traffic_stats['upload'])}\n"
        f"  📈 Всего: {format_bytes(traffic_stats['total'])}\n\n"
        f"🆔 Ваш VLESS ID:\n`{vless_id}`\n\n"
        f"🔗 Ссылка для настройки:\n`{vless_link}`"
    )
    
    # Создаем кнопки
    keyboard = [
        [InlineKeyboardButton("📱 QR-код", callback_data="qr_code")],
        [InlineKeyboardButton("🔄 Обновить", callback_data="my_subscription")],
        [InlineKeyboardButton("💰 Продлить подписку", callback_data="prices")],
        [InlineKeyboardButton("◀️ Назад", callback_data="back_to_main")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Отвечаем на запрос
    await query.edit_message_text(
        text=text,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def show_qr_code(update: Update, context: CallbackContext):
    """Генерирует и отправляет QR-код для VLESS-конфигурации"""
    query = update.callback_query
    user_id = update.effective_user.id
    
    # Получаем активные подписки
    active_subs = database.get_active_subscriptions(user_id)
    
    if not active_subs:
        # Нет активных подписок
        await query.edit_message_text(
            "У вас нет активных подписок. Выберите тарифный план для покупки.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("💰 Тарифы и оплата", callback_data="prices"),
                InlineKeyboardButton("◀️ Назад", callback_data="back_to_main")
            ]])
        )
        return
    
    # Берем первую активную подписку
    sub = active_subs[0]
    
    # Получаем VLESS-ID
    vless_id = sub['data'].get('vless_id')
    
    if not vless_id:
        await query.answer("Ошибка: отсутствует ID конфигурации", show_alert=True)
        return
    
    # Генерируем VLESS-ссылку
    email = f"user_{user_id}_{sub['id']}"
    vless_link = xray_manager.generate_vless_link(vless_id, email)
    
    # Генерируем QR-код
    qr_image = generate_vless_qr(vless_link, title=f"VPN - {email}")
    
    # Сначала отвечаем на callback-запрос, чтобы убрать часы загрузки
    await query.answer()
    
    # Отправляем новое сообщение с QR-кодом
    await context.bot.send_photo(
        chat_id=update.effective_chat.id,
        photo=InputFile(qr_image, filename="vless_config.png"),
        caption=(
            f"🔹 *QR-код для настройки VLESS*\n\n"
            f"Отсканируйте этот QR-код в вашем VPN-клиенте для автоматической настройки подключения.\n\n"
            f"👉 *ID:* `{vless_id}`\n\n"
            f"👉 *Ссылка:*\n`{vless_link}`"
        ),
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("◀️ Назад к подписке", callback_data="my_subscription")
        ]])
    )
    
    # Удаляем предыдущее сообщение с меню
    await query.delete_message()

async def show_traffic_stats(update: Update, context: CallbackContext):
    """Показывает статистику использования трафика"""
    query = update.callback_query
    user_id = update.effective_user.id
    
    # Получаем активные подписки
    active_subs = database.get_active_subscriptions(user_id)
    
    if not active_subs:
        # Нет активных подписок
        await query.answer("У вас нет активных подписок", show_alert=True)
        return
    
    # Берем первую активную подписку
    sub = active_subs[0]
    
    # Получаем статистику трафика
    email = f"user_{user_id}_{sub['id']}"
    traffic_stats = xray_manager.get_user_traffic(email)
    
    # Формируем текст со статистикой
    text = (
        f"🔹 *Статистика использования трафика*\n\n"
        f"📊 Текущий период:\n"
        f"  ⬇️ Скачано: {format_bytes(traffic_stats['download'])}\n"
        f"  ⬆️ Загружено: {format_bytes(traffic_stats['upload'])}\n"
        f"  📈 Всего: {format_bytes(traffic_stats['total'])}\n\n"
    )
    
    # Создаем кнопки
    keyboard = [
        [InlineKeyboardButton("🔄 Обновить", callback_data="traffic")],
        [InlineKeyboardButton("◀️ Назад", callback_data="my_subscription")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Отвечаем на запрос
    await query.edit_message_text(
        text=text,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def show_support_info(update: Update, context: CallbackContext):
    """Показывает информацию о связи с поддержкой"""
    query = update.callback_query
    
    text = (
        "🔹 *Поддержка*\n\n"
        "Если у вас возникли вопросы или проблемы с использованием VPN, "
        "пожалуйста, свяжитесь с нами одним из следующих способов:\n\n"
        "✉️ Email: support@example.com\n"
        "💬 Telegram: @support_username\n\n"
        "Мы ответим вам в ближайшее время!"
    )
    
    keyboard = [
        [InlineKeyboardButton("📝 Написать в поддержку", url="https://t.me/support_username")],
        [InlineKeyboardButton("◀️ Назад", callback_data="back_to_main")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        text=text,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

# Админские функции
async def show_admin_panel(update: Update, context: CallbackContext):
    """Показывает панель администратора"""
    query = update.callback_query
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await query.answer("У вас нет прав администратора", show_alert=True)
        return
    
    # Получаем статистику
    users_count = len(database.get_all_users())
    active_subs = 0
    expired_subs = 0
    
    for user in database.get_all_users():
        user_subs = database.get_user_subscriptions(user['id'])
        for sub in user_subs:
            if sub['is_active'] and sub['expires_at'] > time.time():
                active_subs += 1
            else:
                expired_subs += 1
    
    text = (
        f"🔹 *Панель администратора*\n\n"
        f"👥 Пользователей: {users_count}\n"
        f"✅ Активных подписок: {active_subs}\n"
        f"❌ Истекших подписок: {expired_subs}\n\n"
        f"Выберите действие:"
    )
    
    keyboard = [
        [InlineKeyboardButton("👥 Управление пользователями", callback_data="admin_users")],
        [InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton("⚙️ Настройки сервера", callback_data="admin_server")],
        [InlineKeyboardButton("◀️ Назад", callback_data="back_to_main")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        text=text,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

# Обработчик callback-запросов
async def button_handler(update: Update, context: CallbackContext):
    """Обрабатывает нажатия на inline-кнопки"""
    query = update.callback_query
    data = query.data
    
    # Сначала отвечаем на callback-запрос, чтобы убрать часы загрузки
    await query.answer()
    
    # Обрабатываем разные типы callback-запросов
    if data == "back_to_main":
        await show_main_menu(update, context)
    
    elif data == "prices":
        await show_prices(update, context)
    
    elif data.startswith("select_plan_"):
        await select_plan(update, context)
    
    elif data == "buy_subscription":
        await show_prices(update, context)
    
    elif data.startswith("pay_"):
        await process_payment(update, context)
    
    elif data.startswith("check_payment_"):
        await check_payment_manually(update, context)
    
    elif data == "my_subscription":
        await show_subscription(update, context)
    
    elif data == "qr_code":
        await show_qr_code(update, context)
    
    elif data == "traffic":
        await show_traffic_stats(update, context)
    
    elif data == "support":
        await show_support_info(update, context)
    
    elif data == "admin":
        await show_admin_panel(update, context)
    
    elif data == "activate_trial":
        await activate_trial(update, context)
    
    # Можно добавить другие обработчики здесь

# Обработчик звезд Telegram
async def handle_stars_payment(update: Update, context: CallbackContext):
    """Обработка событий оплаты звездами Telegram"""
    if update.message and update.message.forward_from and update.message.forward_from.id == 777000:
        # Это сообщение о звездах от Telegram
        user_id = update.effective_user.id
        
        # Примерный формат сообщения: "You received 50 stars from User"
        message_text = update.message.text
        
        if "received" in message_text and "stars" in message_text:
            try:
                # Извлекаем количество звезд
                parts = message_text.split()
                stars_index = parts.index("received") + 1
                stars_count = int(parts[stars_index])
                
                logger.info(f"Получена оплата звездами от пользователя {user_id}: {stars_count} звезд")
                
                # Получаем активные ожидающие платежи пользователя
                user_payments = database.get_user_payments(user_id)
                pending_payments = [p for p in user_payments if p['status'] == 'pending' and p.get('currency') == 'STARS']
                
                if pending_payments:
                    # Берем последний ожидающий платеж
                    payment = pending_payments[-1]
                    payment_id = payment['payment_id']
                    days = payment['subscription_days']
                    
                    # Расчет необходимого количества звезд
                    required_stars = payment.get('price_stars', int(payment['amount'] * 10))
                    
                    if stars_count >= required_stars:
                        # Достаточно звезд для оплаты
                        # Обновляем статус платежа
                        database.update_payment_status(payment_id, 'paid')
                        
                        # Создаем подписку
                        subscription = database.add_subscription(user_id, days, payment_id)
                        
                        if subscription:
                            # Создаем пользователя в Xray
                            email = f"user_{user_id}_{subscription['id']}"
                            xray_user = xray_manager.add_user(email)
                            
                            # Добавляем UUID в данные подписки
                            subscription['data']['vless_id'] = xray_user['id']
                            
                            # Отправляем сообщение об успешной оплате
                            await update.message.reply_text(
                                "✅ *Оплата звездами получена!*\n\n"
                                f"Ваша подписка на {days} дней активирована.",
                                parse_mode='Markdown',
                                reply_markup=InlineKeyboardMarkup([[
                                    InlineKeyboardButton("🔑 Моя подписка", callback_data="my_subscription")
                                ]])
                            )
                            return
                        
                    else:
                        # Недостаточно звезд
                        await update.message.reply_text(
                            f"❌ Получено {stars_count} звезд, но для оплаты подписки нужно {required_stars} звезд.",
                            reply_markup=InlineKeyboardMarkup([[
                                InlineKeyboardButton("💰 Просмотреть тарифы", callback_data="prices")
                            ]])
                        )
                        return
            
            except Exception as e:
                logger.error(f"Error processing Stars payment: {e}")
                
        # Если не удалось обработать платеж
        await update.message.reply_text(
            "Спасибо за звезды! К сожалению, мы не смогли найти соответствующий платеж. "
            "Пожалуйста, выберите тарифный план и выполните оплату через меню бота.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("💰 Просмотреть тарифы", callback_data="prices")
            ]])
        )

# Функция для запуска бота
def main():
    """Запускает бота"""
    # Получаем токен из конфигурации
    bot_token = config.get_bot_token()
    
    if not bot_token:
        logger.error("Bot token not configured. Set it in config.yaml")
        return
    
    # Создаем экземпляр приложения
    application = Application.builder().token(bot_token).build()
    
    # Добавляем обработчики команд
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("subscription", lambda update, context: show_main_menu(update, context)))
    application.add_handler(CommandHandler("prices", lambda update, context: show_prices(update, {"callback_query": update})))
    application.add_handler(CommandHandler("qr", lambda update, context: show_qr_code(update, {"callback_query": update})))
    application.add_handler(CommandHandler("traffic", lambda update, context: show_traffic_stats(update, {"callback_query": update})))
    application.add_handler(CommandHandler("admin", lambda update, context: show_admin_panel(update, {"callback_query": update})))
    
    # Добавляем обработчик callback-запросов
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # Добавляем обработчик для звезд Telegram
    application.add_handler(MessageHandler(filters.TEXT & filters.FORWARDED, handle_stars_payment))
    
    logger.info("Бот настроен с поддержкой автогенерации ключей Reality, пробного периода и оплаты через USDT и звезды Telegram")
    
    # Запускаем бота
    logger.info("Starting bot...")
    application.run_polling()

if __name__ == "__main__":
    main() 