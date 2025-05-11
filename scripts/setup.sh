#!/bin/bash

# Скрипт для установки и настройки VPN Telegram бота
# Поддерживаемые ОС: Ubuntu 22.04+, Debian 11+

set -e

# Проверка прав
if [ "$EUID" -ne 0 ]; then
  echo "Для установки требуются права администратора. Запустите скрипт с sudo."
  exit 1
fi

# Запрос параметров установки
read -p "Введите токен вашего Telegram бота (из BotFather): " BOT_TOKEN
read -p "Введите ID администратора (ваш Telegram ID): " ADMIN_ID
read -p "Введите домен сервера (или IP адрес, если домена нет): " SERVER_DOMAIN
read -p "Введите IP адрес сервера: " SERVER_IP

# Цвета для вывода
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Функция для вывода
print_status() {
  echo -e "${GREEN}[+] $1${NC}"
}

print_warning() {
  echo -e "${YELLOW}[!] $1${NC}"
}

print_error() {
  echo -e "${RED}[-] $1${NC}"
}

# Проверка OS
check_os() {
  print_status "Проверка операционной системы..."
  
  if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS=$ID
    VERSION=$VERSION_ID
  else
    print_error "Невозможно определить операционную систему"
    exit 1
  fi
  
  if [ "$OS" != "ubuntu" ] && [ "$OS" != "debian" ]; then
    print_error "Этот скрипт поддерживает только Ubuntu и Debian"
    exit 1
  fi
  
  print_status "Операционная система: $OS $VERSION"
}

# Установка необходимых пакетов
install_dependencies() {
  print_status "Установка необходимых пакетов..."
  
  apt update
  apt install -y \
    python3 \
    python3-pip \
    python3-venv \
    git \
    ufw
  
  print_status "Необходимые пакеты установлены"
}

# Установка и настройка Xray
install_xray() {
  print_status "Установка Xray..."
  
  # Вызов скрипта установки Xray
  bash ./install_xray.sh
  
  # Получение ключей Reality из файла, созданного скриптом установки Xray
  if [ -f "xray_keys.txt" ]; then
    source xray_keys.txt
    print_status "Ключи Reality загружены"
  else
    print_error "Файл с ключами Reality не найден"
    exit 1
  fi
}

# Клонирование и настройка бота
setup_bot() {
  print_status "Установка VPN Telegram бота..."
  
  # Создание директории для бота
  mkdir -p /opt/vpnbot
  
  # Копирование файлов бота
  cp -r ../* /opt/vpnbot/
  
  # Переход в директорию бота
  cd /opt/vpnbot
  
  # Создание виртуального окружения Python
  python3 -m venv venv
  
  # Активация виртуального окружения и установка зависимостей
  source venv/bin/activate
  pip install -r requirements.txt
  
  # Создание конфигурационного файла
  cp config.yaml.example config.yaml
  
  # Заполнение конфигурационного файла
  sed -i "s/your_bot_token_here/$BOT_TOKEN/g" config.yaml
  sed -i "s/123456789/$ADMIN_ID/g" config.yaml
  sed -i "s/your_server_ip_here/$SERVER_IP/g" config.yaml
  sed -i "s/example.com/$SERVER_DOMAIN/g" config.yaml
  
  # Включаем автоматическую генерацию ключей Reality
  sed -i 's/auto_generate_keys: false/auto_generate_keys: true/g' config.yaml
  
  print_status "Бот установлен и настроен"
}

# Настройка автозапуска
setup_autostart() {
  print_status "Настройка автозапуска..."
  
  # Копирование systemd сервиса
  cp scripts/vpnbot.service /etc/systemd/system/
  
  # Перезагрузка systemd
  systemctl daemon-reload
  
  # Включение и запуск службы
  systemctl enable vpnbot
  systemctl start vpnbot
  
  print_status "Автозапуск настроен"
}

# Настройка файрвола
configure_firewall() {
  print_status "Настройка файрвола..."
  
  # Разрешаем SSH и HTTPS
  ufw allow ssh
  ufw allow 443/tcp
  
  # Включаем файрвол
  if [ "$(ufw status | grep -c "Status: active")" -eq 0 ]; then
    print_warning "Включение файрвола. Убедитесь, что порт SSH (22) разрешен!"
    echo "y" | ufw enable
  fi
  
  print_status "Файрвол настроен"
}

# Вывод информации об установке
show_info() {
  print_status "Установка завершена!"
  print_status "VPN Telegram бот запущен и настроен для автозапуска"
  print_status "Проверить статус: systemctl status vpnbot"
  print_status "Остановить бота: systemctl stop vpnbot"
  print_status "Запустить бота: systemctl start vpnbot"
  print_status "Журнал логов: journalctl -u vpnbot -f"
  print_status ""
  print_status "Теперь вы можете найти вашего бота в Telegram и начать им пользоваться!"
}

# Основная функция
main() {
  print_status "Начало установки VPN Telegram бота..."
  
  check_os
  install_dependencies
  install_xray
  setup_bot
  setup_autostart
  configure_firewall
  show_info
}

main 