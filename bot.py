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
AWAITING_PROTOCOL = 'AWAITING_PROTOCOL'
AWAITING_SERVER = 'AWAITING_SERVER'
CHECKING_PAYMENT = 'CHECKING_PAYMENT'

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
    
    # Если доступно несколько серверов, показываем выбор сервера
    available_servers = xray_manager.get_available_servers()
    if len(available_servers) > 1:
        # Сохраняем в контексте, что это пробный период
        context.user_data['is_trial'] = True
        context.user_data['trial_days'] = config.get_trial_days()
        
        # Переходим к выбору сервера
        await show_server_selection(update, context)
        return
    
    # Если только один сервер, активируем пробный период на нем
    server_id = None
    if available_servers:
        server_id = available_servers[0]['id']
    
    # Создаем пробную подписку
    trial_days = config.get_trial_days()
    subscription = database.add_subscription(
        user_id=user_id,
        days=trial_days,
        payment_id=None,  # Без платежа
        server_id=server_id  # Добавляем ID сервера
    )
    
    if subscription:
        # Отмечаем подписку как пробную
        subscription['is_trial'] = True
        
        # Создаем пользователя в Xray
        email = f"trial_user_{user_id}_{subscription['id']}"
        xray_user = xray_manager.add_user(email, server_id=server_id)
        
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
        
        # Получаем информацию о сервере
        server_info = ""
        if 'server_id' in sub and sub['server_id']:
            server = config.get_server_by_id(sub['server_id'])
            if server:
                server_name = server.get('name', f"Server {sub['server_id']}")
                server_info = f"🌍 Сервер: {server_name}\n"
        
        title = (
            f"🔹 *Ваша подписка активна*\n\n"
            f"{server_info}"
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

async def show_server_selection(update: Update, context: CallbackContext):
    """Показывает меню выбора сервера"""
    query = update.callback_query
    if query:
        await query.answer()
    
    # Получаем список доступных серверов
    available_servers = xray_manager.get_available_servers()
    
    if not available_servers:
        # Если серверов нет, сообщаем об ошибке
        message = "❌ Нет доступных серверов в данный момент. Пожалуйста, попробуйте позже."
        if query:
            await query.edit_message_text(message)
        else:
            await update.message.reply_text(message)
        return
    
    # Если только один сервер, пропускаем выбор
    if len(available_servers) == 1:
        server = available_servers[0]
        context.user_data['selected_server_id'] = server['id']
        
        # Проверяем, был ли выбран план или это пробный период
        if 'selected_plan' in context.user_data:
            await show_payment_options(update, context)
        elif 'is_trial' in context.user_data and context.user_data['is_trial']:
            # Активируем пробный период на выбранном сервере
            await process_trial_activation(update, context)
        return
    
    # Создаем клавиатуру с кнопками выбора сервера
    keyboard = []
    for server in available_servers:
        location_info = f" ({server['location']})" if 'location' in server else ""
        button_text = f"🌍 {server['name']}{location_info}"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"server_{server['id']}")])
    
    # Добавляем кнопку возврата
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back_to_plans")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Заголовок сообщения
    title = "🌍 *Выберите сервер*\n\n"
    
    # Добавляем описание серверов, если оно есть
    for server in available_servers:
        if 'description' in server and server['description']:
            title += f"*{server['name']}*: {server['description']}\n"
    
    if query:
        await query.edit_message_text(
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

async def process_server_selection(update: Update, context: CallbackContext):
    """Обработка выбора сервера"""
    query = update.callback_query
    await query.answer()
    
    # Извлекаем ID сервера из данных обратного вызова
    server_id = query.data.split('_')[1]
    
    # Сохраняем выбранный сервер в данных пользователя
    context.user_data['selected_server_id'] = server_id
    
    # Проверяем следующий шаг: платеж или пробный период
    if 'is_trial' in context.user_data and context.user_data['is_trial']:
        # Активируем пробный период на выбранном сервере
        await process_trial_activation(update, context)
    else:
        # Переходим к выбору способа оплаты
        await show_payment_options(update, context)

async def process_trial_activation(update: Update, context: CallbackContext):
    """Активация пробного периода на выбранном сервере"""
    query = update.callback_query
    user_id = update.effective_user.id
    
    # Получаем ID выбранного сервера и количество дней пробного периода
    server_id = context.user_data.get('selected_server_id')
    trial_days = context.user_data.get('trial_days', config.get_trial_days())
    
    # Очищаем данные о пробном периоде
    if 'is_trial' in context.user_data:
        del context.user_data['is_trial']
    if 'trial_days' in context.user_data:
        del context.user_data['trial_days']
    
    # Создаем пробную подписку
    subscription = database.add_subscription(
        user_id=user_id,
        days=trial_days,
        payment_id=None,  # Без платежа
        server_id=server_id
    )
    
    if subscription:
        # Отмечаем подписку как пробную
        subscription['is_trial'] = True
        
        # Создаем пользователя в Xray
        email = f"trial_user_{user_id}_{subscription['id']}"
        xray_user = xray_manager.add_user(email, server_id=server_id)
        
        # Добавляем UUID в данные подписки
        subscription['data']['vless_id'] = xray_user['id']
        
        # Получаем имя сервера для отображения
        server_name = "VPN"
        server = config.get_server_by_id(server_id)
        if server:
            server_name = server.get('name', f"Server {server_id}")
        
        # Обновляем информацию пользователя
        await query.edit_message_text(
            f"✅ *Поздравляем!*\n\n"
            f"Ваш пробный период на сервере *{server_name}* активирован на {trial_days} дней.\n"
            f"Теперь вы можете получить конфигурацию для подключения.",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔑 Моя подписка", callback_data="my_subscription")
            ]])
        )
    else:
        await query.edit_message_text(
            "❌ Произошла ошибка при активации пробного периода",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Вернуться в меню", callback_data="start")
            ]])
        )

# Обработчики для покупки и управления подпиской
async def show_prices(update: Update, context: CallbackContext):
    """Показывает список тарифных планов"""
    query = None
    if update.callback_query:
        query = update.callback_query
        await query.answer()
    
    plans = get_subscription_plans()
    
    if not plans:
        message = "Тарифные планы не настроены. Пожалуйста, свяжитесь с администратором."
        if query:
            await query.edit_message_text(message)
        else:
            await update.message.reply_text(message)
        return
    
    # Создаем клавиатуру с кнопками выбора плана
    keyboard = []
    for plan in plans:
        days = plan.get('days', 0)
        price = plan.get('price', 0)
        title = plan.get('title', f"{days} дней")
        
        # Создаем текст кнопки
        button_text = f"{title} - ${price}"
        
        # Если включены Telegram Stars, показываем цену в звездах
        if config.is_telegram_stars_enabled() and 'price_stars' in plan:
            button_text += f" / {plan['price_stars']} ⭐"
        
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"plan_{days}")])
    
    # Добавляем кнопку возврата в главное меню
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="start")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message = (
        "💰 *Тарифные планы*\n\n"
        "Выберите подходящий тарифный план для подписки:\n\n"
    )
    
    # Добавляем информацию о способах оплаты
    payment_info = []
    
    if config.get_crypto_bot_token():
        payment_info.append("• 💎 Криптовалюта через CryptoBot")
    
    if config.is_telegram_stars_enabled():
        payment_info.append("• ⭐ Telegram Stars")
    
    if payment_info:
        message += "Доступные способы оплаты:\n" + "\n".join(payment_info)
    
    if query:
        await query.edit_message_text(
            text=message,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            text=message,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )

async def select_plan(update: Update, context: CallbackContext):
    """Обработка выбора тарифного плана"""
    query = update.callback_query
    await query.answer()
    
    # Извлекаем количество дней из данных обратного вызова
    days = int(query.data.split('_')[1])
    
    # Находим выбранный план
    plans = get_subscription_plans()
    selected_plan = next((p for p in plans if p.get('days') == days), None)
    
    if not selected_plan:
        await query.edit_message_text(
            "Выбранный тариф не найден. Пожалуйста, выберите другой тариф.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Назад к тарифам", callback_data="prices")
            ]])
        )
        return
    
    # Сохраняем выбранный план в данных пользователя
    context.user_data['selected_plan'] = selected_plan
    
    # Проверяем количество доступных серверов
    available_servers = xray_manager.get_available_servers()
    
    if len(available_servers) > 1:
        # Если больше одного сервера, показываем выбор сервера
        await show_server_selection(update, context)
    else:
        # Если только один сервер или нет серверов
        if available_servers:
            context.user_data['selected_server_id'] = available_servers[0]['id']
        else:
            context.user_data['selected_server_id'] = None
        
        # Переходим к выбору способа оплаты
        await show_payment_options(update, context)

async def show_payment_options(update: Update, context: CallbackContext, plan=None):
    """Показывает доступные способы оплаты"""
    query = update.callback_query
    await query.answer()
    
    # Используем план из аргументов или из данных пользователя
    if not plan and 'selected_plan' in context.user_data:
        plan = context.user_data['selected_plan']
    
    if not plan:
        await query.edit_message_text(
            "Произошла ошибка при выборе тарифа. Пожалуйста, попробуйте снова.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Назад к тарифам", callback_data="prices")
            ]])
        )
        return
    
    # Проверяем выбранный сервер
    server_id = context.user_data.get('selected_server_id')
    
    # Получаем информацию о сервере для отображения
    server_info = ""
    if server_id:
        server = config.get_server_by_id(server_id)
        if server:
            server_name = server.get('name', f"Server {server_id}")
            server_location = server.get('location', '')
            
            server_info = f"🌍 Сервер: *{server_name}*"
            if server_location:
                server_info += f" ({server_location})"
            server_info += "\n\n"
    
    # Создаем список доступных способов оплаты
    keyboard = []
    
    # Добавляем кнопку оплаты криптовалютой, если настроен CryptoBot
    if config.get_crypto_bot_token():
        keyboard.append([
            InlineKeyboardButton(
                f"💎 Криптовалюта (${plan['price']})", 
                callback_data=f"pay_crypto_{plan['days']}"
            )
        ])
    
    # Добавляем кнопку оплаты Telegram Stars, если включено
    if config.is_telegram_stars_enabled() and 'price_stars' in plan:
        keyboard.append([
            InlineKeyboardButton(
                f"⭐ Telegram Stars ({plan['price_stars']} звезд)", 
                callback_data=f"pay_stars_{plan['days']}"
            )
        ])
    
    # Добавляем кнопку возврата
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="prices")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Формируем текст сообщения
    title = plan.get('title', f"{plan['days']} дней")
    price = plan.get('price', 0)
    
    message = (
        f"💰 *Выбранный тариф: {title}*\n\n"
        f"{server_info}"
        f"Стоимость: ${price}\n\n"
        f"Выберите способ оплаты:"
    )
    
    await query.edit_message_text(
        text=message,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def process_payment(update: Update, context: CallbackContext):
    """Обработка запроса на оплату"""
    query = update.callback_query
    await query.answer()
    
    # Получаем данные из callback_data
    parts = query.data.split('_')
    payment_method = parts[1]
    days = int(parts[2])
    
    # Находим соответствующий тарифный план
    plans = get_subscription_plans()
    plan = next((p for p in plans if p.get('days') == days), None)
    
    if not plan:
        await query.edit_message_text(
            "Выбранный тариф не найден. Пожалуйста, выберите другой тариф.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Назад к тарифам", callback_data="prices")
            ]])
        )
        return
    
    # Получаем ID выбранного сервера
    server_id = context.user_data.get('selected_server_id')
    
    # Получаем информацию о сервере для отображения
    server_info = ""
    if server_id:
        server = config.get_server_by_id(server_id)
        if server:
            server_name = server.get('name', f"Server {server_id}")
            server_info = f"🌍 Сервер: *{server_name}*\n\n"
    
    user_id = update.effective_user.id
    username = update.effective_user.username or f"user_{user_id}"
    
    if payment_method == "crypto":
        # Генерируем уникальный ID платежа
        payment_id = f"crypto_{int(time.time())}_{user_id}"
        
        # Записываем платеж в базу данных
        database.record_payment(
            user_id=user_id,
            payment_id=payment_id,
            amount=plan['price'],
            currency='USD',
            status='pending',
            subscription_days=days,
            server_id=server_id
        )
        
        # Создаем инвойс через CryptoBot
        try:
            payment_url = await payment_manager.create_crypto_invoice(
                payment_id=payment_id,
                amount=plan['price'],
                description=f"Подписка VPN на {days} дней"
            )
            
            if payment_url:
                # Сохраняем данные платежа в контексте
                context.user_data[AWAITING_PAYMENT] = payment_id
                
                keyboard = [
                    [InlineKeyboardButton("💰 Оплатить", url=payment_url)],
                    [InlineKeyboardButton("🔄 Проверить оплату", callback_data=f"check_payment_{payment_id}")],
                    [InlineKeyboardButton("🔙 Назад", callback_data="prices")]
                ]
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(
                    f"💰 *Оплата криптовалютой*\n\n"
                    f"{server_info}"
                    f"Тариф: {plan.get('title', f'{days} дней')}\n"
                    f"Сумма: ${plan['price']}\n\n"
                    f"Нажмите кнопку 'Оплатить' для перехода к оплате через CryptoBot. "
                    f"После оплаты нажмите 'Проверить оплату'.",
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
                
                # Запускаем задачу для автоматической проверки платежа
                job_name = f"payment_{payment_id}_{user_id}"
                context.job_queue.run_repeating(
                    check_payment_job,
                    interval=30,  # каждые 30 секунд
                    first=30,     # первая проверка через 30 секунд
                    data={
                        'payment_id': payment_id,
                        'chat_id': update.effective_chat.id,
                        'message_id': query.message.message_id,
                        'user_id': user_id,
                        'server_id': server_id
                    },
                    name=job_name
                )
                
                # Запоминаем имя задачи в контексте
                context.user_data['payment_job'] = job_name
                
            else:
                await query.edit_message_text(
                    "Произошла ошибка при создании платежа. Пожалуйста, попробуйте позже или выберите другой метод оплаты.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔙 Назад", callback_data="prices")
                    ]])
                )
                
        except Exception as e:
            logger.error(f"Error creating crypto payment: {e}")
            await query.edit_message_text(
                "Произошла ошибка при создании платежа. Пожалуйста, попробуйте позже или выберите другой метод оплаты.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 Назад", callback_data="prices")
                ]])
            )
    
    elif payment_method == "stars":
        # Для оплаты Telegram Stars переходим в специальный обработчик
        selected_plan = {'days': days, 'price_stars': plan.get('price_stars', 0)}
        context.user_data['selected_plan'] = selected_plan
        context.user_data['server_id'] = server_id
        await handle_stars_payment(update, context)

async def check_payment_manually(update: Update, context: CallbackContext):
    """Ручная проверка статуса платежа"""
    query = update.callback_query
    await query.answer("Проверяем статус платежа...")
    
    # Получаем ID платежа из callback_data
    payment_id = query.data.split('_')[2]
    user_id = update.effective_user.id
    
    # Получаем информацию о платеже из базы данных
    payment = database.get_payment(payment_id)
    
    if not payment:
        await query.edit_message_text(
            "Информация о платеже не найдена. Пожалуйста, попробуйте оплатить снова.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Назад", callback_data="prices")
            ]])
        )
        return
    
    # Проверяем статус платежа
    if payment['status'] == 'completed':
        # Платеж уже обработан
        await query.edit_message_text(
            "✅ Платеж успешно обработан. Ваша подписка активирована.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔑 Моя подписка", callback_data="my_subscription")
            ]])
        )
        return
    
    # Проверяем платеж в платежной системе
    payment_verified = False
    
    if payment_id.startswith('crypto'):
        # Проверка через CryptoBot
        payment_verified = await payment_manager.check_crypto_payment(payment_id)
    
    if payment_verified:
        # Обновляем статус платежа в базе данных
        database.update_payment_status(payment_id, 'completed')
        
        # Получаем информацию о сервере
        server_id = payment.get('server_id')
        
        # Создаем подписку
        subscription = database.add_subscription(
            user_id=user_id,
            days=payment['subscription_days'],
            payment_id=payment_id,
            server_id=server_id
        )
        
        if subscription:
            # Создаем пользователя в Xray
            email = f"user_{user_id}_{subscription['id']}"
            xray_user = xray_manager.add_user(email, server_id=server_id)
            
            # Добавляем UUID в данные подписки
            subscription['data']['vless_id'] = xray_user['id']
            
            # Получаем название сервера для отображения
            server_name = "VPN"
            if server_id:
                server = config.get_server_by_id(server_id)
                if server:
                    server_name = server.get('name', f"Server {server_id}")
            
            # Останавливаем задачу автоматической проверки, если она запущена
            if 'payment_job' in context.user_data:
                try:
                    current_jobs = context.job_queue.get_jobs_by_name(context.user_data['payment_job'])
                    for job in current_jobs:
                        job.schedule_removal()
                    del context.user_data['payment_job']
                except Exception as e:
                    logger.error(f"Error removing payment job: {e}")
            
            # Очищаем состояние ожидания платежа
            if AWAITING_PAYMENT in context.user_data:
                del context.user_data[AWAITING_PAYMENT]
            
            # Уведомляем пользователя об успешной оплате
            await query.edit_message_text(
                f"✅ *Оплата успешно проведена!*\n\n"
                f"Ваша подписка на сервере *{server_name}* активирована на {payment['subscription_days']} дней.\n"
                f"Нажмите кнопку ниже, чтобы просмотреть данные для подключения.",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔑 Моя подписка", callback_data="my_subscription")
                ]])
            )
        else:
            await query.edit_message_text(
                "✅ Оплата прошла успешно, но возникла ошибка при активации подписки. Пожалуйста, обратитесь в поддержку.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🆘 Поддержка", callback_data="support")
                ]])
            )
    else:
        # Платеж не найден или не подтвержден
        await query.edit_message_text(
            "❌ Платеж не найден или еще не подтвержден. Пожалуйста, убедитесь, что вы завершили оплату и попробуйте проверить снова через некоторое время.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Проверить снова", callback_data=f"check_payment_{payment_id}")],
                [InlineKeyboardButton("🔙 Назад", callback_data="prices")]
            ])
        )

async def check_payment_job(context: CallbackContext):
    """Автоматическая периодическая проверка статуса платежа"""
    job_data = context.job.data
    
    payment_id = job_data.get('payment_id')
    chat_id = job_data.get('chat_id')
    message_id = job_data.get('message_id')
    user_id = job_data.get('user_id')
    server_id = job_data.get('server_id')
    
    # Проверяем, существует ли платеж и его статус
    payment = database.get_payment(payment_id)
    
    if not payment or payment['status'] == 'completed':
        # Если платеж не найден или уже обработан, останавливаем задачу
        context.job.schedule_removal()
        return
    
    # Проверяем платеж в платежной системе
    payment_verified = False
    
    if payment_id.startswith('crypto'):
        # Проверка через CryptoBot
        payment_verified = await payment_manager.check_crypto_payment(payment_id)
    
    if payment_verified:
        # Обновляем статус платежа в базе данных
        database.update_payment_status(payment_id, 'completed')
        
        # Создаем подписку
        subscription = database.add_subscription(
            user_id=user_id,
            days=payment['subscription_days'],
            payment_id=payment_id,
            server_id=server_id
        )
        
        if subscription:
            # Создаем пользователя в Xray
            email = f"user_{user_id}_{subscription['id']}"
            xray_user = xray_manager.add_user(email, server_id=server_id)
            
            # Добавляем UUID в данные подписки
            subscription['data']['vless_id'] = xray_user['id']
            
            # Получаем название сервера для отображения
            server_name = "VPN"
            if server_id:
                server = config.get_server_by_id(server_id)
                if server:
                    server_name = server.get('name', f"Server {server_id}")
            
            # Уведомляем пользователя об успешной оплате
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=f"✅ *Оплата успешно проведена!*\n\n"
                         f"Ваша подписка на сервере *{server_name}* активирована на {payment['subscription_days']} дней.\n"
                         f"Нажмите кнопку ниже, чтобы просмотреть данные для подключения.",
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔑 Моя подписка", callback_data="my_subscription")
                    ]])
                )
            except Exception as e:
                logger.error(f"Error updating message after payment: {e}")
        
        # Останавливаем задачу после успешной обработки платежа
        context.job.schedule_removal()

# Обработчики для управления подпиской
async def show_subscription(update: Update, context: CallbackContext):
    """Показывает информацию о подписке пользователя и конфигурации VPN"""
    query = None
    if update.callback_query:
        query = update.callback_query
        await query.answer()
    
    user_id = update.effective_user.id
    
    # Получаем активные подписки пользователя
    active_subs = database.get_active_subscriptions(user_id)
    
    if not active_subs:
        # У пользователя нет активных подписок
        message = (
            "У вас нет активных подписок VPN.\n\n"
            "Выберите тарифный план для покупки новой подписки."
        )
        
        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("💰 Тарифы и оплата", callback_data="prices")],
            [InlineKeyboardButton("🔙 Назад", callback_data="start")]
        ])
        
        if query:
            await query.edit_message_text(message, reply_markup=reply_markup)
        else:
            await update.message.reply_text(message, reply_markup=reply_markup)
        return
    
    # Если у пользователя несколько активных подписок, показываем список для выбора
    if len(active_subs) > 1:
        keyboard = []
        for sub in active_subs:
            # Получаем информацию о сервере
            server_name = "VPN"
            if 'server_id' in sub and sub['server_id']:
                server = config.get_server_by_id(sub['server_id'])
                if server:
                    server_name = server.get('name', f"Server {sub['server_id']}")
            
            keyboard.append([
                InlineKeyboardButton(
                    f"{server_name}", 
                    callback_data=f"subscription_{sub['id']}"
                )
            ])
        
        keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="start")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message = "У вас несколько активных подписок VPN. Выберите подписку для просмотра:"
        
        if query:
            await query.edit_message_text(message, reply_markup=reply_markup)
        else:
            await update.message.reply_text(message, reply_markup=reply_markup)
        return
    
    # Если только одна активная подписка, показываем ее
    subscription = active_subs[0]
    
    # Получаем информацию о сервере
    server_info = ""
    server_id = subscription.get('server_id')
    if server_id:
        server = config.get_server_by_id(server_id)
        if server:
            server_name = server.get('name', f"Server {server_id}")
            server_location = server.get('location', '')
            
            server_info = f"🌍 Сервер: *{server_name}*"
            if server_location:
                server_info += f" ({server_location})"
            server_info += "\n\n"
    
    # Формируем информацию о сроке действия подписки
    expiry_date = datetime.fromtimestamp(subscription['expires_at'])
    time_left = subscription['expires_at'] - time.time()
    
    # Получаем данные для подключения
    vless_id = subscription['data'].get('vless_id', 'unknown')
    
    # Генерируем ссылки на конфигурацию
    email = f"user_{user_id}_{subscription['id']}"
    reality_link = xray_manager.generate_vless_link(vless_id, email, "reality", server_id)
    websocket_link = xray_manager.generate_vless_link(vless_id, email, "websocket", server_id)
    
    # Формируем сообщение с информацией о подписке
    message = (
        f"🔹 *Ваша подписка*\n\n"
        f"{server_info}"
        f"⏳ Осталось: {format_time_left(time_left)}\n"
        f"📅 Истекает: {expiry_date.strftime('%d.%m.%Y')}\n\n"
        f"🔑 *Данные для подключения:*\n\n"
        f"🆔 UUID: `{vless_id}`\n\n"
        f"Выберите протокол для получения настроек:"
    )
    
    # Создаем клавиатуру с кнопками для конфигураций и QR-кодов
    keyboard = [
        [
            InlineKeyboardButton("⚡ VLESS Reality", callback_data=f"protocol_reality_{subscription['id']}"),
            InlineKeyboardButton("🌐 WebSocket+TLS", callback_data=f"protocol_websocket_{subscription['id']}")
        ],
        [
            InlineKeyboardButton("📱 QR Reality", callback_data=f"qr_reality_{subscription['id']}"),
            InlineKeyboardButton("📱 QR WebSocket", callback_data=f"qr_websocket_{subscription['id']}")
        ],
        [InlineKeyboardButton("🔙 Назад", callback_data="start")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if query:
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='Markdown')

async def show_protocol_config(update: Update, context: CallbackContext):
    """Показывает конфигурацию для выбранного протокола"""
    query = update.callback_query
    await query.answer()
    
    # Извлекаем данные из callback_data
    parts = query.data.split('_')
    protocol = parts[1]
    subscription_id = parts[2]
    
    user_id = update.effective_user.id
    
    # Находим подписку по ID
    active_subs = database.get_active_subscriptions(user_id)
    subscription = next((s for s in active_subs if s['id'] == subscription_id), None)
    
    if not subscription:
        await query.edit_message_text(
            "Подписка не найдена или истекла. Пожалуйста, вернитесь в главное меню.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Назад", callback_data="start")
            ]])
        )
        return
    
    # Получаем ID сервера
    server_id = subscription.get('server_id')
    
    # Генерируем ссылку на конфигурацию
    vless_id = subscription['data'].get('vless_id', 'unknown')
    email = f"user_{user_id}_{subscription['id']}"
    
    config_link = xray_manager.generate_vless_link(vless_id, email, protocol, server_id)
    
    # Формируем название протокола для отображения
    protocol_name = "VLESS Reality" if protocol == "reality" else "VLESS WebSocket+TLS"
    
    message = (
        f"🔹 *Конфигурация {protocol_name}*\n\n"
        f"Скопируйте ссылку ниже и импортируйте ее в приложение VLESS/V2ray:\n\n"
        f"`{config_link}`\n\n"
        f"Или используйте QR-код для быстрой настройки."
    )
    
    keyboard = [
        [InlineKeyboardButton(f"📱 QR-код", callback_data=f"qr_{protocol}_{subscription_id}")],
        [InlineKeyboardButton("🔙 Назад к подписке", callback_data="my_subscription")],
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        message,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def show_qr_code(update: Update, context: CallbackContext):
    """Показывает QR-код для выбранного протокола"""
    query = update.callback_query
    await query.answer()
    
    # Извлекаем данные из callback_data
    parts = query.data.split('_')
    protocol = parts[1]
    subscription_id = parts[2]
    
    user_id = update.effective_user.id
    
    # Находим подписку по ID
    active_subs = database.get_active_subscriptions(user_id)
    subscription = next((s for s in active_subs if s['id'] == subscription_id), None)
    
    if not subscription:
        await query.edit_message_text(
            "Подписка не найдена или истекла. Пожалуйста, вернитесь в главное меню.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Назад", callback_data="start")
            ]])
        )
        return
    
    # Получаем ID сервера
    server_id = subscription.get('server_id')
    
    # Генерируем ссылку для QR-кода
    vless_id = subscription['data'].get('vless_id', 'unknown')
    email = f"user_{user_id}_{subscription['id']}"
    
    config_link = xray_manager.generate_vless_link(vless_id, email, protocol, server_id)
    
    # Генерируем QR-код
    qr_image = generate_vless_qr(config_link)
    
    if qr_image:
        # Преобразуем изображение в байты для отправки
        img_byte_arr = io.BytesIO()
        qr_image.save(img_byte_arr, format='PNG')
        img_byte_arr.seek(0)
        
        # Формируем название протокола для отображения
        protocol_name = "VLESS Reality" if protocol == "reality" else "VLESS WebSocket+TLS"
        
        # Отправляем QR-код
        await query.message.reply_photo(
            photo=InputFile(img_byte_arr),
            caption=f"📱 QR-код для {protocol_name}\n\nОтсканируйте этот QR-код с помощью вашего VPN-клиента для автоматической настройки."
        )
        
        # Возвращаем к информации о подписке
        await show_subscription(update, context)
    else:
        await query.edit_message_text(
            "Произошла ошибка при генерации QR-кода. Пожалуйста, попробуйте позже.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Назад", callback_data="my_subscription")
            ]])
        )

async def show_traffic_stats(update: Update, context: CallbackContext):
    """Показывает статистику использования трафика"""
    query = None
    if update.callback_query:
        query = update.callback_query
        await query.answer()
    
    user_id = update.effective_user.id
    
    # Получаем активные подписки пользователя
    active_subs = database.get_active_subscriptions(user_id)
    
    if not active_subs:
        message = "У вас нет активных подписок для проверки статистики."
        reply_markup = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔙 Назад", callback_data="start")
        ]])
        
        if query:
            await query.edit_message_text(message, reply_markup=reply_markup)
        else:
            await update.message.reply_text(message, reply_markup=reply_markup)
        return
    
    # Если у пользователя несколько активных подписок, показываем список для выбора
    if len(active_subs) > 1:
        keyboard = []
        for sub in active_subs:
            # Получаем информацию о сервере
            server_name = "VPN"
            if 'server_id' in sub and sub['server_id']:
                server = config.get_server_by_id(sub['server_id'])
                if server:
                    server_name = server.get('name', f"Server {sub['server_id']}")
            
            keyboard.append([
                InlineKeyboardButton(
                    f"📊 {server_name}", 
                    callback_data=f"traffic_{sub['id']}"
                )
            ])
        
        keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="start")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message = "У вас несколько активных подписок. Выберите подписку для просмотра статистики:"
        
        if query:
            await query.edit_message_text(message, reply_markup=reply_markup)
        else:
            await update.message.reply_text(message, reply_markup=reply_markup)
        return
    
    # Если только одна активная подписка, показываем ее статистику
    subscription = active_subs[0]
    subscription_id = subscription['id']
    
    # Проверяем, была ли это конкретная подписка, выбранная пользователем
    if query and query.data.startswith('traffic_'):
        subscription_id = query.data.split('_')[1]
        subscription = next((s for s in active_subs if s['id'] == subscription_id), None)
        if not subscription:
            await query.edit_message_text(
                "Подписка не найдена или истекла. Пожалуйста, вернитесь в главное меню.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 Назад", callback_data="start")
                ]])
            )
            return
    
    # Получаем ID сервера
    server_id = subscription.get('server_id')
    
    # Получаем информацию о сервере
    server_info = ""
    if server_id:
        server = config.get_server_by_id(server_id)
        if server:
            server_name = server.get('name', f"Server {server_id}")
            server_location = server.get('location', '')
            
            server_info = f"🌍 Сервер: *{server_name}*"
            if server_location:
                server_info += f" ({server_location})"
            server_info += "\n\n"
    
    # Получаем статистику использования трафика из базы данных
    traffic_used = subscription['data'].get('traffic_used', 0)
    
    # Получаем реальную статистику из Xray
    email = f"user_{user_id}_{subscription['id']}"
    xray_traffic = xray_manager.get_user_traffic(email, server_id)
    
    # Обновляем данные в базе, если есть реальные данные
    total_traffic = xray_traffic['total']
    if total_traffic > 0:
        subscription['data']['traffic_used'] = total_traffic
    
    # Форматируем данные для отображения
    uplink = format_bytes(xray_traffic['uplink'])
    downlink = format_bytes(xray_traffic['downlink'])
    total = format_bytes(xray_traffic['total'])
    
    # Формируем сообщение со статистикой
    message = (
        f"📊 *Статистика использования трафика*\n\n"
        f"{server_info}"
        f"📤 Отправлено: {uplink}\n"
        f"📥 Получено: {downlink}\n"
        f"📉 Всего: {total}\n\n"
        f"Статистика обновляется в реальном времени."
    )
    
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="start")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if query:
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='Markdown')

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
    """Обработчик нажатий на кнопки"""
    query = update.callback_query
    data = query.data
    
    if data == "start":
        await show_main_menu(update, context)
    
    elif data == "prices":
        await show_prices(update, context)
    
    elif data == "buy_subscription":
        await show_prices(update, context)
    
    elif data == "my_subscription":
        await show_subscription(update, context)
    
    elif data == "traffic":
        await show_traffic_stats(update, context)
    
    elif data == "qr_code":
        await show_subscription(update, context)  # Переходим к выбору протокола
    
    elif data == "support":
        await show_support_info(update, context)
    
    elif data == "admin":
        await show_admin_panel(update, context)
    
    elif data == "activate_trial":
        await activate_trial(update, context)
    
    elif data.startswith("plan_"):
        await select_plan(update, context)
    
    elif data.startswith("pay_"):
        await process_payment(update, context)
    
    elif data.startswith("check_payment_"):
        await check_payment_manually(update, context)
    
    elif data.startswith("protocol_"):
        await show_protocol_config(update, context)
    
    elif data.startswith("qr_"):
        await show_qr_code(update, context)
    
    elif data.startswith("subscription_"):
        # ID подписки передается в context и затем используется в show_subscription
        subscription_id = data.split('_')[1]
        context.user_data['selected_subscription_id'] = subscription_id
        await show_subscription(update, context)
    
    elif data.startswith("traffic_"):
        await show_traffic_stats(update, context)
    
    elif data == "back_to_plans":
        # Если возвращаемся из выбора сервера, очищаем выбранный сервер
        if 'selected_server_id' in context.user_data:
            del context.user_data['selected_server_id']
        await show_prices(update, context)
    
    elif data.startswith("server_"):
        # Обработка выбора сервера
        await process_server_selection(update, context)
    
    elif data == "show_server_selection":
        await show_server_selection(update, context)
    
    else:
        await query.answer("Неизвестная команда")

# Обработчик звезд Telegram
async def handle_stars_payment(update: Update, context: CallbackContext):
    """Обработка оплаты через Telegram Stars"""
    query = update.callback_query
    
    if not config.is_telegram_stars_enabled():
        await query.edit_message_text(
            "Оплата через Telegram Stars временно недоступна. Пожалуйста, выберите другой способ оплаты.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Назад", callback_data="prices")
            ]])
        )
        return
    
    # Получаем план и информацию о сервере
    selected_plan = context.user_data.get('selected_plan')
    server_id = context.user_data.get('selected_server_id')
    
    if not selected_plan or 'price_stars' not in selected_plan:
        await query.edit_message_text(
            "Произошла ошибка при обработке платежа. Пожалуйста, выберите тариф снова.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Назад", callback_data="prices")
            ]])
        )
        return
    
    # Генерируем уникальный ID платежа
    user_id = update.effective_user.id
    payment_id = f"stars_{int(time.time())}_{user_id}"
    
    # Получаем информацию о сервере для отображения
    server_info = ""
    if server_id:
        server = config.get_server_by_id(server_id)
        if server:
            server_name = server.get('name', f"Server {server_id}")
            server_info = f"🌍 Сервер: *{server_name}*\n\n"
    
    # Создаем запись о платеже в базе данных
    database.record_payment(
        user_id=user_id,
        payment_id=payment_id,
        amount=selected_plan.get('price_stars', 0),
        currency='STARS',
        status='pending',
        subscription_days=selected_plan.get('days', 30),
        server_id=server_id
    )
    
    # Сохраняем ID платежа в контексте
    context.user_data[AWAITING_PAYMENT] = payment_id
    
    # Создаем сообщение с инструкциями для оплаты звездами
    stars_amount = selected_plan.get('price_stars', 0)
    message = (
        f"⭐ *Оплата с помощью Telegram Stars*\n\n"
        f"{server_info}"
        f"Тариф: {selected_plan.get('days')} дней\n"
        f"Стоимость: {stars_amount} звезд\n\n"
        f"Для оплаты, пожалуйста, отправьте {stars_amount} звезд в этот чат.\n"
        f"После отправки звезд, нажмите кнопку 'Я отправил звезды' для подтверждения платежа."
    )
    
    keyboard = [
        [InlineKeyboardButton("✅ Я отправил звезды", callback_data=f"check_stars_{payment_id}")],
        [InlineKeyboardButton("🔙 Отмена", callback_data="prices")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Обновляем сообщение с инструкциями для оплаты
    await query.edit_message_text(
        text=message,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    
    # Устанавливаем состояние ожидания подтверждения оплаты
    context.user_data[CHECKING_PAYMENT] = True

# Функция для запуска бота
def main():
    """Основная функция для запуска бота"""
    # Создаем экземпляр приложения
    application = Application.builder().token(config.get_bot_token()).build()
    
    # Добавляем обработчики команд
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("subscription", lambda update, context: show_subscription(update, context)))
    application.add_handler(CommandHandler("prices", lambda update, context: show_prices(update, context)))
    application.add_handler(CommandHandler("qr", lambda update, context: show_subscription(update, context)))
    application.add_handler(CommandHandler("traffic", lambda update, context: show_traffic_stats(update, context)))
    application.add_handler(CommandHandler("support", lambda update, context: show_support_info(update, context)))
    application.add_handler(CommandHandler("admin", lambda update, context: show_admin_panel(update, context) if is_admin(update.effective_user.id) else start_command(update, context)))
    
    # Добавляем обработчик для кнопок
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # Добавляем обработчик для всех сообщений
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, lambda update, context: show_main_menu(update, context)))
    
    # Запускаем бота
    application.run_polling()

if __name__ == "__main__":
    main() 