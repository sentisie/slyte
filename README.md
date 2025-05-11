# VPN Telegram Bot

Telegram бот для автоматической выдачи VLESS (Reality или WebSocket) конфигураций с системой платежей и управления подписками.

## Возможности

- Автоматическая выдача VLESS конфигов после оплаты
- Поддержка Reality и WebSocket + TLS
- Система управления подписками
- **Бесплатный пробный период (3 дня) для новых пользователей**
- **Автоматическая генерация ключей Reality**
- **Оплата звездами Telegram и USDT**
- Интеграция с платежными системами (CryptoBot, YooMoney)
- Ограничение числа устройств по IP
- Мониторинг использования
- Автоматические уведомления об истечении подписки

## Требования

- Python 3.8+
- Сервер с Ubuntu 22.04+ или Debian 11+
- Установленный Xray
- Домен (для WebSocket + TLS)

## Установка

1. Клонировать репозиторий:

```bash
git clone https://github.com/your-username/vpnbot.git
cd vpnbot
```

2. Установить зависимости:

```bash
pip install -r requirements.txt
```

3. Создать конфигурационный файл:

```bash
cp config.yaml.example config.yaml
```

4. Отредактировать `config.yaml`, указав:

   - Токен вашего Telegram бота (получите его от @BotFather)
   - IP адрес и домен вашего сервера
   - ID администраторов (получите их от @userinfobot)
   - Ключи для Reality
   - Данные платежных систем

5. Установить и настроить Xray:

```bash
bash scripts/install_xray.sh
```

6. Запустить бота:

```bash
python bot.py
```

## Настройка автозапуска

Для настройки автозапуска используйте systemd:

```bash
sudo cp scripts/vpnbot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable vpnbot
sudo systemctl start vpnbot
```

## Оплата подписки

Бот поддерживает следующие методы оплаты:

- **Звезды Telegram** - пользователи могут отправлять звезды прямо в чате с ботом
- **USDT** - оплата через CryptoBot в токенах USDT (Tether)
- **Криптовалюты** - BTC, ETH, TON через CryptoBot
- **YooMoney** - для российских пользователей

## Пробный период

Для новых пользователей доступен бесплатный пробный период на 3 дня. Пользователь может активировать его нажав на кнопку "Активировать пробный период" в главном меню бота.

## Использование

1. Отправьте `/start` своему боту
2. Следуйте инструкциям для активации пробного периода или покупки подписки
3. После активации вы автоматически получите VLESS конфигурацию
4. Используйте ссылку или QR-код для настройки клиента

## Команды для администраторов

- `/admin` - Меню администратора
- `/stats` - Статистика использования
- `/users` - Управление пользователями
- `/settings` - Настройки сервера

## Клиенты для подключения

- [V2rayN](https://github.com/2dust/v2rayN) (Windows)
- [V2rayNG](https://github.com/2dust/v2rayNG) (Android)
- [Shadowrocket](https://apps.apple.com/us/app/shadowrocket/id932747118) (iOS)
- [V2rayU](https://github.com/yanue/V2rayU) (macOS)

## Лицензия

MIT
 