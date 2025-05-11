#!/bin/bash

# Скрипт для установки Xray на сервер
# Поддерживаемые ОС: Ubuntu 22.04+, Debian 11+

set -e

# Проверка прав
if [ "$EUID" -ne 0 ]; then
  echo "Для установки требуются права администратора. Запустите скрипт с sudo."
  exit 1
fi

# Определение директорий
XRAY_CONFIG_DIR="/etc/xray"
XRAY_LOG_DIR="/var/log/xray"
CERT_DIR="/etc/ssl/xray"

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
    curl \
    wget \
    unzip \
    apt-transport-https \
    ca-certificates \
    gnupg \
    lsb-release \
    jq
  
  print_status "Необходимые пакеты установлены"
}

# Установка Xray
install_xray() {
  print_status "Установка Xray..."
  
  # Создание необходимых директорий
  mkdir -p "$XRAY_CONFIG_DIR"
  mkdir -p "$XRAY_LOG_DIR"
  mkdir -p "$CERT_DIR"
  
  # Скачивание и установка скрипта установки Xray
  bash -c "$(curl -L https://github.com/XTLS/Xray-install/raw/main/install-release.sh)" @ install
  
  # Проверка успешной установки
  if [ ! -f /usr/local/bin/xray ]; then
    print_error "Не удалось установить Xray"
    exit 1
  fi
  
  print_status "Xray успешно установлен"
}

# Генерация ключей для Reality
generate_keys() {
  print_status "Генерация ключей для Reality..."
  
  # Генерация ключевой пары для Reality
  KEY_PAIR=$(/usr/local/bin/xray x25519)
  PRIVATE_KEY=$(echo "$KEY_PAIR" | grep "Private" | awk -F': ' '{print $2}')
  PUBLIC_KEY=$(echo "$KEY_PAIR" | grep "Public" | awk -F': ' '{print $2}')
  
  # Генерация Short ID
  SHORT_ID=$(openssl rand -hex 8)
  
  echo "Private Key: $PRIVATE_KEY"
  echo "Public Key: $PUBLIC_KEY"
  echo "Short ID: $SHORT_ID"
  
  # Сохранение ключей в файл
  echo "REALITY_PRIVATE_KEY=$PRIVATE_KEY" > xray_keys.txt
  echo "REALITY_PUBLIC_KEY=$PUBLIC_KEY" >> xray_keys.txt
  echo "REALITY_SHORT_ID=$SHORT_ID" >> xray_keys.txt
  
  print_status "Ключи Reality сгенерированы и сохранены в xray_keys.txt"
}

# Настройка файрвола
configure_firewall() {
  print_status "Настройка файрвола..."
  
  # Установка ufw, если еще не установлен
  apt install -y ufw
  
  # Настройка правил
  ufw allow ssh
  ufw allow 443/tcp
  
  # Включение файрвола, если еще не включен
  if [ "$(ufw status | grep -c "Status: active")" -eq 0 ]; then
    print_warning "Включение файрвола. Убедитесь, что порт SSH (22) разрешен!"
    echo "y" | ufw enable
  fi
  
  print_status "Файрвол настроен"
}

# Создание systemd службы для Xray
setup_service() {
  print_status "Настройка systemd службы..."
  
  # Служба уже должна быть создана установщиком Xray
  systemctl enable xray
  systemctl restart xray
  
  print_status "Служба Xray настроена и запущена"
}

# Основная функция
main() {
  print_status "Начало установки Xray..."
  
  check_os
  install_dependencies
  install_xray
  generate_keys
  configure_firewall
  setup_service
  
  print_status "Установка Xray завершена!"
  print_status "Ключи Reality находятся в файле xray_keys.txt"
  print_status "Статус службы Xray:"
  systemctl status xray --no-pager
}

main 