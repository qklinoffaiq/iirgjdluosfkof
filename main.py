import vk_api
from vk_api.bot_longpoll import VkBotLongPoll, VkBotEventType
import time
import threading
import json
import os
import requests
import config
from config import MESSAGE_CONFIG, main_photo, group_token, group_id
from datetime import datetime
admin_ids = []

# Глобальные настройки
cd_min = config.cd_min
interval_sec = config.interval_sec

import logging

# Настройка логирования в файл с меткой времени
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Путь к базе данных пользователей
USERS_DB = 'users_db.json'

# Инициализация базы данных
if not os.path.exists(USERS_DB):
    with open(USERS_DB, 'w', encoding='utf-8') as f:
        json.dump({}, f, ensure_ascii=False, indent=4)

# Функция для загрузки данных пользователей
def load_users():
    try:
        with open(USERS_DB, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

# Функция для сохранения данных пользователей
def save_users(data):
    with open(USERS_DB, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

# Централизованная функция получения роли
def get_role(user_id):
    users = load_users()
    return users.get(str(user_id), {}).get('role', 'user')

# Проверка прав
def has_permission(user_id, level):
    role = get_role(user_id)
    if level == 'dev':
        return role == 'dev'
    elif level == 'admin':
        return role in ['admin', 'dev']
    return False

# Обновление статистики пользователя
def update_user_stats(user_id, action=None):
    users = load_users()
    user_id_str = str(user_id)
    if user_id_str not in users:
        users[user_id_str] = {
            "role": "user",
            "osn_photo_count": 0,
            "osn_text_count": 0,
            "total_messages": 0,
            "last_message": ""
        }
    if action == "osn_photo":
        users[user_id_str]["osn_photo_count"] += 1
    elif action == "osn_text":
        users[user_id_str]["osn_text_count"] += 1
    elif action == "command":
        users[user_id_str]["total_messages"] += 1
    users[user_id_str]["last_message"] = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | {action if action else 'message'}"
    save_users(users)

def get_help_text(role):
    user_commands = (
        "📋 Основные команды:\n"
        "🔹 .пинг — проверить, работает ли бот\n"
        "🔹 .стата — посмотреть свою статистику\n"
    )
    
    admin_commands = (
        "🔸 Административные команды:\n"
        "🔹 .редтекст [номер] [текст] — редактировать дополнительный текст\n"
        "🔹 .добтекст [текст] — добавить дополнительный текст\n"
        "🔹 .удтекст [номер] — удалить дополнительный текст\n"
        "🔹 .рассылка — запустить рассылку\n"
        "🔹 .список — показать количество чатов\n"
        "🔹 .ид — узнать ID текущего чата\n"
        "🔹 .инфо — показать текущие настройки\n"
        "🔹 .хелп — показать это сообщение\n"
        "🔹 .тест — отправить тестовое сообщение\n"
        "🔹 .допсписок — показать список доп. текстов\n"
        "🔹 .уст — добавить текущий чат в рассылку\n"
        "🔹 .инфочат — получить информацию о чате\n"
        "🔹 .добид [число] — добавить указанное количество чатов в список\n"
        "🔹 .делид [число] — удалить указанное количество чатов с конца списка\n"
        "🔹 .добфото [номер] — добавить фото к тексту\n"
        "🔹 .удфото [номер] — удалить фото у текста\n"
    )
    
    dev_commands = (
        "🔧 Команды разработчика:\n"
        "🔹 .разраб [id/@/ответ] — выдать/снять права разработчика\n"
        "🔹 .редоснтекст [текст] — изменить основной текст рассылки\n"
        "🔹 .редоснфото — изменить основное фото рассылки\n"
        "🔹 .стафф — показать состав персонала\n"
        "🔹 .админчат — установить текущий чат как административный\n"
    )
    
    full_text = user_commands
    if role in ['admin', 'dev']:
        full_text += "\n" + admin_commands
    if role == 'dev':
        full_text += "\n" + dev_commands
    
    return full_text.strip()

# Импорт datetime после его использования
additional_texts = []  # Дополнительные тексты
additional_texts_separator = "\n\n"  # Разделитель для дополнительных текстов
additional_photos_by_text = {}  # Словарь для хранения вложений по текстам
photo_wait_queue = {}           # Очередь ожидания фото от пользователей
# pending_delid_requests = {}    # Удалено — больше не нужно
# pending_dobid_requests = {}    # Удалено — больше не нужно

# Загружаем основное фото из конфига
main_photo = 'photos/main_photo.jpg'

data_file = 'data.json'

data_file = 'data.json'

try:
    if os.path.exists(data_file):
        with open(data_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        message_text = data.get('message_text', "Текст для рассылки")
        chat_ids = data.get('chat_ids', [])[:]
        admin_chat = data.get('admin_chat', None)
        additional_texts = data.get('additional_texts', [])
        additional_photos_by_text = data.get('additional_photos_by_text', {})
    else:
        message_text = "Текст для рассылки"
        chat_ids = []
        admin_chat = None
        additional_texts = []
        additional_photos_by_text = {}
except Exception as e:
    logger.error(f"Ошибка загрузки data.json: {e}. Используются значения по умолчанию.")
    message_text = "Текст для рассылки"
    chat_ids = []
    admin_chat = None
    additional_texts = []
    additional_photos_by_text = {}

vk_session = vk_api.VkApi(token=group_token)
vk = vk_session.get_api()

# Инициализируем переменную для хранения загруженного фото
uploaded_photo = None

# Попытка создать Long Poll, но игнорировать ошибку, если Long Poll не включен
try:
    longpoll = VkBotLongPoll(vk_session, group_id)
    longpoll_enabled = True
except vk_api.exceptions.ApiError as e:
    print(f"[!] Ошибка инициализации Long Poll: {e}. Возможно, в настройках группы не включен Long Poll API.")
    longpoll_enabled = False

# Функция для загрузки фото в ВКонтакте
def upload_photo_to_vk(photo_path):
    if not os.path.exists(photo_path):
        print(f"[!] Файл фото не найден: {photo_path}")
        return None
    try:
        upload = vk_api.VkUpload(vk_session)
        photo = upload.photo_messages(photo_path)[0]
        attachment = f"photo{photo['owner_id']}_{photo['id']}"
        print(f"[+] Фото успешно загружено: {attachment}")
        return attachment
    except Exception as e:
        print(f"[!] Ошибка загрузки фото в ВК: {e}")
        return None

def upload_photo_to_vk_from_memory(photo_content):
    try:
        # Создаем временное имя файла для загрузки из памяти
        upload = vk_api.VkUpload(vk_session)
        # Создаем временный файл в памяти
        import io
        photo_file = io.BytesIO(photo_content)
        photo_file.name = 'photo.jpg'
        photo = upload.photo_messages(photo_file)[0]
        attachment = f"photo{photo['owner_id']}_{photo['id']}"
        print(f"[+] Фото успешно загружено из памяти: {attachment}")
        return attachment
    except Exception as e:
        print(f"[!] Ошибка загрузки фото из памяти в ВК: {e}")
        return None

# Загружаем фото при старте, если путь указан
if main_photo:
    uploaded_photo = upload_photo_to_vk(main_photo)
    if not uploaded_photo:
        print("[!] Не удалось загрузить фото, будет отправляться без вложения.")


reset_event = threading.Event()

def save_data():
    # Исключаем admin_chat из списка, если он там есть
    if admin_chat in chat_ids:
        chat_ids.remove(admin_chat)
    try:
        with open(data_file, 'w', encoding='utf-8') as f:
            json.dump({
                'message_text': message_text,
                'chat_ids': chat_ids,
                'admin_chat': admin_chat,
                'additional_texts': additional_texts,
                'additional_photos_by_text': additional_photos_by_text
            }, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"[!] Ошибка сохранения data.json: {e}")

def send_message(chat_id, text, attachment=None):
    # Максимальная длина сообщения для ВКонтакте (с запасом)
    MAX_MESSAGE_LENGTH = 16000
    
    # Если текст слишком длинный, разбиваем его на части
    if text and len(text) > MAX_MESSAGE_LENGTH:
        # Разбиваем текст на части по границам строк, если возможно
        parts = []
        current_part = ""
        
        # Разделяем текст на строки и собираем части
        for line in text.split('\n'):
            # Если добавление строки превысит лимит, отправляем текущую часть
            if len(current_part) + len(line) + 1 > MAX_MESSAGE_LENGTH:  # +1 для символа новой строки
                if current_part:
                    parts.append(current_part)
                current_part = line
            else:
                if current_part:
                    current_part += '\n' + line
                else:
                    current_part = line
        
        # Добавляем последнюю часть
        if current_part:
            parts.append(current_part)
            
        # Отправляем все части
        responses = []
        for i, part in enumerate(parts):
            # Для последней части сохраняем вложение
            current_attachment = attachment if i == len(parts) - 1 else None
            try:
                params = {
                    'peer_id': chat_id,
                    'random_id': 0,
                    'message': part
                }
                if current_attachment:
                    params['attachment'] = current_attachment
                    
                response = vk.messages.send(**params)
                responses.append(response)
                logging.info(f"Chat {chat_id}: Часть сообщения {i+1}/{len(parts)} отправлена.")
                time.sleep(0.1)  # Небольшая задержка между отправкой частей
            except Exception as e:
                error_msg = str(e)
                
                # Обработка ошибки: пользователь исключён из беседы
                if 'the user was kicked out of the conversation' in error_msg:
                    if chat_id in chat_ids:
                        chat_ids.remove(chat_id)
                        save_data()
                    logging.info(f"Chat {chat_id}: Участник исключён из беседы. Чат удалён из списка рассылки.")
                    return None
                
                # Обработка ошибки доступа к чату
                elif 'Ошибка доступа к чату' in error_msg or 'You don\'t have access to this chat' in error_msg:
                    logging.warning(f"Chat {chat_id}: Ошибка доступа. Рассылка приостановлена.")
                    return 'access_error'
                
                # Обработка ошибки ограничения на запись в чат
                elif 'You are restricted to write to a chat' in error_msg or 'code 983' in error_msg:
                    if chat_id in chat_ids:
                        chat_ids.remove(chat_id)
                        save_data()
                    logging.info(f"Chat {chat_id}: Ограничение на запись в чат. Чат удалён из списка рассылки.")
                    return None
                
                # Другие ошибки
                else:
                    print(f"[ERROR] Chat {chat_id}: Произошла ошибка при отправке части {i+1}: {e}")
                    # Продолжаем отправку остальных частей
        
        return responses if responses else None
    
    # Обычная отправка короткого сообщения
    try:
        params = {
            'peer_id': chat_id,
            'random_id': 0
        }
        if text:
            params['message'] = text
        if attachment:
            params['attachment'] = attachment
        
        # Попытка отправить сообщение через API ВКонтакте
        response = vk.messages.send(**params)
        
        # Логирование успешной отправки
        logging.info(f"Chat {chat_id}: Сообщение отправлено.")
        return response
        
    except Exception as e:
        error_msg = str(e)
        
        # Обработка ошибки: пользователь исключён из беседы
        if 'the user was kicked out of the conversation' in error_msg:
            # Удаляем chat_id из списка активных чатов
            if chat_id in chat_ids:
                chat_ids.remove(chat_id)
                save_data()  # Сохраняем изменения в data.json
            # Логируем информацию
            logging.info(f"Chat {chat_id}: Участник исключён из беседы. Чат удалён из списка рассылки.")
            return None
        
        # Обработка ошибки доступа к чату (например, потеря прав администратора)
        elif 'Ошибка доступа к чату' in error_msg or 'You don\'t have access to this chat' in error_msg:
            # НЕ удаляем chat_id, только останавливаем рассылку
            logging.warning(f"Chat {chat_id}: Ошибка доступа. Рассылка приостановлена.")
            # Сохраняем состояние — можно возобновить позже вручную или по таймеру
            return 'access_error'  # Специальный флаг для остановки рассылки
        
        # Обработка ошибки ограничения на запись в чат
        elif 'You are restricted to write to a chat' in error_msg or 'code 983' in error_msg:
            # Удаляем chat_id из списка активных чатов
            if chat_id in chat_ids:
                chat_ids.remove(chat_id)
                save_data()  # Сохраняем изменения в data.json
            # Логируем информацию
            logging.info(f"Chat {chat_id}: Ограничение на запись в чат. Чат удалён из списка рассылки.")
            return None
        
        # Другие ошибки
        else:
            print(f"[ERROR] Chat {chat_id}: Произошла ошибка: {e}")
            return None


def broadcast_message():
    while True:
        reset_event.wait(timeout=cd_min * 60)
        reset_event.clear()
        
        # Создаём локальную копию списка чатов для безопасной итерации
        current_chat_ids = [chat_id for chat_id in chat_ids if admin_chat is not None and chat_id != admin_chat and len(str(chat_id)) == 10 and str(chat_id).startswith('2')]
        total_chats = len(current_chat_ids)
        
        if total_chats == 0:
            print("[INFO] Нет чатов для рассылки.")
            continue
            
        # Отправляем начальное сообщение о прогрессе в админ-чат
        progress_message_id = None
        if admin_chat:
            progress_message = f"🚀 Рассылка в процессе...\n\nВсего чатов: {total_chats}\nПрогресс: 0/{total_chats} (0%)\n[░░░░░░░░░░░░░░░░░░░░]"
            result = send_message(admin_chat, progress_message)
            if result and isinstance(result, list) and len(result) > 0:
                progress_message_id = result[0]
        
        sent_count = 0
        # Определяем частоту обновления прогресса (каждые 5 сообщений)
        update_frequency = max(1, total_chats // 20)  # Минимум каждые 1 сообщение, максимум примерно 20 обновлений
        
        for chat_id in current_chat_ids:
            # Отправка дополнительных текстов
            if additional_texts:
                for idx, add_text in enumerate(additional_texts):
                    if add_text.strip():
                        idx_str = str(idx)
                        attachments = additional_photos_by_text.get(idx_str, [])
                        result = send_message(chat_id, add_text.strip(), attachment=','.join(attachments) if attachments else None)
                        
                        # Проверяем, нужно ли остановить рассылку
                        if result == 'access_error':
                            print("[INFO] Рассылка остановлена из-за ошибки доступа.")
                            if admin_chat and progress_message_id:
                                try:
                                    vk.messages.edit(
                                        peer_id=admin_chat,
                                        message_id=progress_message_id,
                                        message="❌ Рассылка остановлена из-за ошибки доступа."
                                    )
                                    logging.info("Сообщение о ошибке доступа отправлено в админ-чат.")
                                except Exception as e:
                                    print(f"[ERROR] Не удалось обновить сообщение о статусе: {e}")
                            break
                        
                        time.sleep(interval_sec)
                
            # Отправка основного сообщения
            result = send_message(chat_id, message_text, attachment=uploaded_photo)
            
            # Проверяем, нужно ли остановить рассылку после основного сообщения
            if result == 'access_error':
                print("[INFO] Рассылка остановлена из-за ошибки доступа.")
                if admin_chat and progress_message_id:
                    try:
                        vk.messages.edit(
                            peer_id=admin_chat,
                            message_id=progress_message_id,
                            message="❌ Рассылка остановлена из-за ошибки доступа."
                        )
                        logging.info("Сообщение о ошибке доступа отправлено в админ-чат.")
                    except Exception as e:
                        print(f"[ERROR] Не удалось обновить сообщение о статусе: {e}")
                break
                
            sent_count += 1
            
            # Обновляем прогресс только при достижении определённой частоты или при завершении
            if admin_chat and progress_message_id and (sent_count % update_frequency == 0 or sent_count == total_chats):
                progress = (sent_count / total_chats) * 100
                filled_bars = int(progress // 5)
                progress_bar = "█" * filled_bars + "░" * (20 - filled_bars)
                progress_message = f"🚀 Рассылка в процессе...\n\nВсего чатов: {total_chats}\nПрогресс: {sent_count}/{total_chats} ({progress:.1f}%)\n[{progress_bar}]"
                try:
                    vk.messages.edit(
                        peer_id=admin_chat,
                        message_id=progress_message_id,
                        message=progress_message
                    )
                    logging.info(f"Обновлено сообщение о прогрессе: {sent_count}/{total_chats}")
                    time.sleep(0.1)  # Небольшая задержка между запросами к API
                except Exception as e:
                    print(f"[ERROR] Не удалось редактировать сообщение: {e}")
                    logging.error(f"Ошибка редактирования сообщения о прогрессе: {e}")
        
        # Редактируем сообщение о завершении
        if admin_chat and progress_message_id and sent_count > 0:
            if sent_count == total_chats:
                final_message = f"✅ Рассылка завершена! Сообщения отправлены во все {total_chats} чатов."
            else:
                final_message = f"✅ Рассылка завершена частично. Сообщения отправлены в {sent_count} из {total_chats} чатов."
            try:
                vk.messages.edit(
                    peer_id=admin_chat,
                    message_id=progress_message_id,
                    message=final_message
                )
                logging.info("Финальное сообщение о завершении рассылки обновлено.")
            except Exception as e:
                print(f"[ERROR] Не удалось редактировать финальное сообщение: {e}")
                logging.error(f"Ошибка при редактировании финального сообщения: {e}")

if 'broadcast_thread' not in globals() or not broadcast_thread.is_alive():
    broadcast_thread = threading.Thread(target=broadcast_message, name="BroadcastThread")
    broadcast_thread.daemon = True
    broadcast_thread.start()

# Основной цикл обработки событий
while True:
    if not longpoll_enabled:
        print("[!] Long Poll не активен. Бот ожидает команды вручную...")
        time.sleep(10) # Пауза перед повторной попыткой
        continue

    try:
        event = longpoll.check()
        if event is None:
            continue
        
        if isinstance(event, list):
            events = event
        else:
            events = [event]
            
        # Проверяем, запущен ли поток рассылки, и перезапускаем его при необходимости
        if 'broadcast_thread' not in globals() or not broadcast_thread.is_alive():
            broadcast_thread = threading.Thread(target=broadcast_message, name="BroadcastThread")
            broadcast_thread.daemon = True
            broadcast_thread.start()

        for event in events:
            if event.type == VkBotEventType.MESSAGE_NEW:
                message = event.obj.message
                chat_id = message['peer_id']
                text = message['text']

                # Все команды работают только для администраторов
                # Проверяем, является ли отправитель администратором по его user_id
                user_id = message['from_id']
                # Обновляем last_message для всех входящих сообщений
                update_user_stats(user_id, 'message')

                # Проверяем, является ли сообщение командой
                if not text.startswith('.'):
                    continue

                # Функция для получения user_id из ссылки, @ или ответа
                def extract_target_user(event):
                    message = event.obj.message
                    text = message['text']
                    # Проверка по ответу на сообщение
                    if 'reply_message' in message:
                        return message['reply_message']['from_id']
                    # Проверка по @-упоминанию
                    if ' @' in text:
                        parts = text.split(' @', 1)
                        mention = parts[1].strip().split()[0]
                        if mention.startswith('id') and mention[2:].isdigit():
                            return int(mention[2:])
                        if mention.startswith('public') and mention[6:].isdigit():
                            return -int(mention[6:])
                        try:
                            response = vk.users.get(user_ids=mention)
                            if response:
                                return response[0]['id']
                        except Exception as e:
                            print(f"[!] Ошибка при получении ID по @: {e}")
                            pass
                    # Проверка по ссылке
                    link_patterns = [
                        'https://vk.com/id', 'https://vk.ru/id',
                        'vk.com/id', 'vk.ru/id',
                        'https://vk.com/public', 'https://vk.ru/public',
                        'vk.com/public', 'vk.ru/public',
                        'id'
                    ]
                    found = False
                    for pattern in link_patterns:
                        if pattern in text:
                            link_part = text.split(pattern)[-1]
                            found = True
                            break
                    if not found and text.strip().startswith('id'):
                        link_part = text.strip().split('id', 1)[-1]
                        found = True
                    
                    if found:
                        # Извлекаем ID до первого нецифрового символа
                        user_id_str = ''
                        for char in link_part:
                            if char.isdigit():
                                user_id_str += char
                            else:
                                break
                        if user_id_str:
                            user_id_num = int(user_id_str)
                            if 'public' in text or (len(link_part) > len(user_id_str) and link_part[len(user_id_str)] == ' ' and 'public' in locals().get('pattern', '')):
                                return -user_id_num
                            else:
                                return user_id_num
                    return None

                # --- Команда .редоснфото ---
                if text.startswith('.') and text.split()[0] == '.редоснфото':
                    if user_id == 574393629:
                        if chat_id != admin_chat:
                            send_message(chat_id, "❌ Эта команда доступна только в админ-чате.")
                            continue
                        if 'attachments' in message and message['attachments']:
                            attachment = message['attachments'][0]
                            if attachment['type'] == 'photo':
                                # Скачиваем фото с максимальным качеством
                                sizes = attachment['photo']['sizes']
                                max_size = max(sizes, key=lambda x: x['width'] * x['height'])
                                photo_url = max_size['url']
                                photo_response = requests.get(photo_url)
                                if photo_response.status_code == 200:
                                    # Сохраняем фото локально
                                    photo_path = os.path.join('photos', 'main_photo.jpg')
                                    os.makedirs('photos', exist_ok=True)
                                    with open(photo_path, 'wb') as f:
                                        f.write(photo_response.content)
                                    # Обновляем main_photo в config.py
                                    config_content = ''
                                    with open('config.py', 'r', encoding='utf-8') as f:
                                        config_content = f.read()
                                    config_content = config_content.replace(f"main_photo = \"{main_photo}\"", f"main_photo = \"photos/main_photo.jpg\"")
                                    with open('config.py', 'w', encoding='utf-8') as f:
                                        f.write(config_content)
                                    # Обновляем пер��менную
                                    main_photo = 'photos/main_photo.jpg'
                                    # Перезагружаем фото
                                    new_uploaded_photo = upload_photo_to_vk(main_photo)
                                    if new_uploaded_photo:
                                        uploaded_photo = new_uploaded_photo
                                        # Обновляем статистику
                                        update_user_stats(user_id, 'osn_photo')
                                        send_message(chat_id, "✅ Основное фото бота успешно обновлено.")
                                    else:
                                        send_message(chat_id, "❌ Не удалось загрузить новое фото.")
                                else:
                                    send_message(chat_id, "❌ Не удалось скачать фото.")
                            else:
                                send_message(chat_id, "❌ Прикрепите именно фото.")
                        else:
                            send_message(chat_id, "❌ Прикрепите фото к сообщению.")
                    else:
                        send_message(chat_id, "❌ У вас нет прав на выполнение этой команды.")

                # --- Команда .разраб ---
                elif text.startswith('.') and text.split()[0] == '.разраб':
                    if user_id == 574393629:
                        target_id = extract_target_user(event)
                        if not target_id:
                            send_message(chat_id, "❌ Укажите пользователя: ответом, @ или ссылкой.")
                            continue
                        users = load_users()
                        user_key = str(target_id)
                        current_role = users.get(user_key, {}).get('role', 'user')
                        if current_role == 'dev':
                            users[user_key]['role'] = 'user'
                            save_users(users)
                            try:
                                user_info = vk.users.get(user_ids=target_id)[0]
                                full_name = f"{user_info['first_name']} {user_info['last_name']}"
                                send_message(chat_id, f"❌ Права разработчика сняты у [id{target_id}|{full_name}]")
                            except Exception as e:
                                send_message(chat_id, f"❌ Права разработчика сняты у пользователя {target_id}. Произошла ошибка при получении имени: {e}")
                        else:
                            users[user_key]['role'] = 'dev'
                            save_users(users)
                            try:
                                user_info = vk.users.get(user_ids=target_id)[0]
                                full_name = f"{user_info['first_name']} {user_info['last_name']}"
                                send_message(chat_id, f"✅ [id{target_id}|{full_name}] назначен(а) разработчиком.")
                            except Exception as e:
                                send_message(chat_id, f"✅ Пользователь {target_id} назначен разработчиком. Произошла ошибка при получении имени: {e}")
                    else:
                        send_message(chat_id, "❌ У вас нет прав на выполнение этой команды.")

                # --- Команда .админ ---
                elif text.startswith('.') and text.split()[0] == '.админ':
                    if not has_permission(user_id, 'dev'):
                        send_message(chat_id, "❌ Доступ запрещён. Только разработчик может выдавать права администратора.")
                        logging.info(f"Попытка использования команды .админ пользователем {user_id} без прав dev.")
                        continue
                    
                    target_id = extract_target_user(event)
                    if not target_id:
                        send_message(chat_id, "❌ Укажите пользователя: ответом, @ или ссылкой.")
                        logging.info(f"Команда .админ: не указан ID пользователя от {user_id}.")
                        continue
                    
                    if user_id == target_id:
                        send_message(chat_id, "❌ Нельзя снимать права администратора с себя через эту команду.")
                        continue
                    
                    users = load_users()
                    user_key = str(target_id)
                    
                    # Автоматическое добавление пользователя в БД с ролью user
                    if user_key not in users:
                        users[user_key] = {
                            "role": "user",
                            "osn_photo_count": 0,
                            "osn_text_count": 0,
                            "total_messages": 0,
                            "last_message": ""
                        }
                        logging.info(f"Пользователь {target_id} автоматически добавлен в users_db.json при выдаче прав администратора")
                    
                    is_admin = users[user_key].get('role') == 'admin'
                    
                    if is_admin:
                        # Снимаем права
                        if target_id in admin_ids:
                            admin_ids.remove(target_id)
                        users[user_key]['role'] = 'user'
                        action = 'remove'
                    else:
                        # Выдаём права
                        if target_id not in admin_ids:
                            admin_ids.append(target_id)
                        users[user_key]['role'] = 'admin'
                        action = 'add'
                    
                    save_users(users)
                    
                    try:
                        target_info = vk.users.get(user_ids=target_id)[0]
                        target_full_name = f"{target_info['first_name']} {target_info['last_name']}"
                        target_link = f"[id{target_id}|{target_full_name}]"
                        
                        admin_info = vk.users.get(user_ids=user_id)[0]
                        admin_full_name = f"{admin_info['first_name']} {admin_info['last_name']}"
                        admin_name = f"[id{user_id}|{admin_full_name}]"
                    except Exception:
                        target_link = f"[id{target_id}|пользователь {target_id}]"
                        admin_name = f"[id{user_id}|пользователь {user_id}]"
                    
                    # Отправляем кликабельное уведомление о назначении
                    if action == 'add':
                        send_message(chat_id, f"✅ {admin_name} выдал права администратора пользователю {target_link}.")
                        logging.info(f"Пользователь {user_id} назначил администратором {target_id}.")
                    else:
                        send_message(chat_id, f"❌ {admin_name} снял права администратора у {target_link}.")
                        logging.info(f"Пользователь {user_id} снял права администратора с {target_id}.")

                # --- Команда .стата ---
                elif text.startswith('.') and text.split()[0] == '.стата':
                    target_id = extract_target_user(event) or user_id
                    try:
                        user_info = vk.users.get(user_ids=target_id)[0]
                        full_name = f"{user_info['first_name']} {user_info['last_name']}"
                    except:
                        full_name = "Пользователь"
                    users = load_users()
                    user_data = users.get(str(target_id), {
                        "role": "user",
                        "osn_photo_count": 0,
                        "osn_text_count": 0,
                        "total_messages": 0,
                        "last_message": "Неизвестно"
                    })
                    role_names = {"user": "Пользователь", "admin": "Администратор", "dev": "Разработчик"}
                    role_display = role_names.get(user_data['role'], "Пользователь")
                    stats_text = (
                        f"👤 Информация о пользователе:\n\n"
                        f"🔹 Имя: {full_name}\n"
                        f"🔹 Роль: {role_display}\n"
                        f"🔹 Изменения текста/фото: {user_data['osn_text_count'] + user_data['osn_photo_count']}\n"
                        f"🔹 Всего сообщений для бота: {user_data['total_messages']}\n"
                        f"🔹 Последнее сообщение: {user_data['last_message']}"
                    )
                    send_message(chat_id, stats_text)
                    update_user_stats(user_id, 'command')

                # --- Команда .стафф ---
                elif text.startswith('.') and text.split()[0] == '.стафф':
                    if user_id == 574393629:
                        users = load_users()
                        devs = []
                        admins = []

                        # Получаем информацию о владельце (разработчике)
                        try:
                            owner_info = vk.users.get(user_ids=574393629)[0]
                            owner_name = f"{owner_info['first_name']} {owner_info['last_name']}"
                            devs.append(f"• [id574393629|{owner_name}]")
                        except:
                            devs.append("• [id574393629|Разработчик]")

                        # Собираем администраторов
                        for uid, data in users.items():
                            if data.get('role') == 'admin':
                                try:
                                    info = vk.users.get(user_ids=int(uid))[0]
                                    name = f"{info['first_name']} {info['last_name']}"
                                    admins.append(f"• [id{uid}|{name}]")
                                except:
                                    admins.append(f"• [id{uid}|Администратор]")

                        staff_text = "🔧 Список персонала бота:\n\nРазработчик:\n" + "\n".join(devs) + "\n\nАдминистраторы:\n" + ("\n".join(admins) if admins else "Нет назначенных администраторов")
                        send_message(chat_id, staff_text)
                    else:
                        send_message(chat_id, "❌ У вас нет прав на выполнение этой команды.")

                # --- Остальные команды ---
                elif text == '.инфочат':
                    if chat_id != admin_chat:
                        send_message(chat_id, "❌ Эта команда доступна только в админ-чате.")
                        continue
                    help_text = (
                        "📋 Информация о чате:\n"
                        "\n"
                        "🔹 ID чата: " + str(chat_id) + "\n"
                        "🔹 ID отправителя: " + str(user_id) + "\n"
                        "🔹 Режим Long Poll: " + ("Включён" if longpoll_enabled else "Отключён или не настроен") + "\n"
                        "🔹 Текущий административный чат: " + (str(admin_chat) if admin_chat else "Не установлен") + "\n"
                        "▫️ Версия бота: 2.0\n"
                    )
                    send_message(chat_id, help_text)

                elif text.startswith('.редтекст'):
                    if chat_id != admin_chat:
                        send_message(chat_id, "❌ Эта команда доступна только в админ-чате.")
                        continue
                    if not has_permission(user_id, 'admin'):
                        send_message(chat_id, "❌ У вас нет прав на выполнение этой команды.")
                        continue
                    try:
                        parts = text.split(' ', 2)
                        if len(parts) < 3:
                            send_message(chat_id, "Неверный формат команды. Используйте: .редтекст [номер] [текст]")
                            continue
                        try:
                            idx = int(parts[1]) - 1
                        except ValueError:
                            send_message(chat_id, "Номер должен быть числом.")
                            continue
                        new_text = parts[2]
                        if idx < 0:
                            send_message(chat_id, "Номер должен быть положительным числом.")
                            continue
                        while len(additional_texts) <= idx:
                            additional_texts.append("")
                        additional_texts[idx] = new_text
                        save_data()
                        send_message(chat_id, f"{new_text}")
                        update_user_stats(user_id, 'command')
                    except Exception as e:
                        send_message(chat_id, "Ошибка при обработке команды.")
                elif text == '.список':
                    if chat_id != admin_chat:
                        send_message(chat_id, "❌ Эта команда доступна только в админ-чате.")
                        continue
                    if not has_permission(user_id, 'admin'):
                        send_message(chat_id, "❌ У вас нет прав на выполнение этой команды.")
                        continue
                    total_chats = len(chat_ids)
                    chat_list = "\n".join(str(cid) for cid in chat_ids if cid != admin_chat)
                    send_message(chat_id, f"Количество чатов для рассылки: {total_chats}\nСписок чатов:\n{chat_list}")
                    update_user_stats(user_id, 'command')
                elif text == '.рассылка':
                    if chat_id != admin_chat:
                        send_message(chat_id, "❌ Эта команда доступна только в админ-чате.")
                        continue
                    if not has_permission(user_id, 'admin'):
                        send_message(chat_id, "❌ У вас нет прав на выполнение этой команды.")
                        continue
                    if admin_chat:
                        if reset_event.is_set():
                            reset_event.clear()
                        reset_event.set()
                        send_message(admin_chat, "Рассылка запущена и таймер сброшен.")
                    update_user_stats(user_id, 'command')
                elif text == '.тест':
                    if chat_id != admin_chat:
                        send_message(chat_id, "❌ Эта команда доступна только в админ-чате.")
                        continue
                    # Отправляем сообщение только в текущий чат
                    if additional_texts:
                        for idx, add_text in enumerate(additional_texts):
                            if add_text.strip():
                                idx_str = str(idx)
                                attachments = additional_photos_by_text.get(idx_str, [])
                                send_message(chat_id, add_text.strip(), attachment=','.join(attachments) if attachments else None)
                                time.sleep(interval_sec)
                    send_message(chat_id, message_text, attachment=uploaded_photo)
                    update_user_stats(user_id, 'command')
                elif text.startswith('.') and text.split()[0] == '.редоснтекст':
                    if chat_id != admin_chat:
                        send_message(chat_id, "❌ Эта команда доступна только в админ-чате.")
                        continue
                    if not has_permission(user_id, 'dev'):
                        send_message(chat_id, "❌ У вас нет прав на выполнение этой команды.")
                        continue
                    try:
                        new_main_text = text.split(' ', 1)[1] if ' ' in text else ''
                        message_text = new_main_text
                        
                        # Проверяем, есть ли прикрепленные фото
                        if 'attachments' in message and message['attachments']:
                            attachment = message['attachments'][0]
                            if attachment['type'] == 'photo':
                                # Получаем фото с максимальным качеством
                                sizes = attachment['photo']['sizes']
                                max_size = max(sizes, key=lambda x: x['width'] * x['height'])
                                photo_url = max_size['url']
                                photo_response = requests.get(photo_url)
                                if photo_response.status_code == 200:
                                    # Сохраняем фото локально
                                    photo_path = os.path.join('photos', 'main_photo.jpg')
                                    os.makedirs('photos', exist_ok=True)
                                    with open(photo_path, 'wb') as f:
                                        f.write(photo_response.content)
                                    # Обновляем main_photo в config.py
                                    config_content = ''
                                    with open('config.py', 'r', encoding='utf-8') as f:
                                        config_content = f.read()
                                    config_content = config_content.replace(f"main_photo = \"{main_photo}\"", f"main_photo = \"photos/main_photo.jpg\"")
                                    with open('config.py', 'w', encoding='utf-8') as f:
                                        f.write(config_content)
                                    # Обновляем переменную
                                    main_photo = 'photos/main_photo.jpg'
                                    # Перезагружаем фото
                                    new_uploaded_photo = upload_photo_to_vk(main_photo)
                                    if new_uploaded_photo:
                                        uploaded_photo = new_uploaded_photo
                                else:
                                    send_message(chat_id, "❌ Не удалось скачать фото.")
                        
                        save_data()
                        # Отправляем только ОДНО сообщение с вложением
                        send_message(chat_id, new_main_text, attachment=uploaded_photo)
                        # Обновляем статистику
                        update_user_stats(user_id, 'osn_text')
                    except (IndexError, ValueError):
                        send_message(chat_id, "Неверный формат команды. Используйте: .редоснтекст [текст]")
                elif text == '.ид':
                    if chat_id != admin_chat:
                        send_message(chat_id, "❌ Эта команда доступна только в админ-чате.")
                        continue
                    if not has_permission(user_id, 'admin'):
                        send_message(chat_id, "❌ У вас нет прав на выполнение этой команды.")
                        continue
                    send_message(chat_id, f"✅ ID этой беседы: {chat_id}")
                    update_user_stats(user_id, 'command')
                elif text == '.инфо':
                    if chat_id != admin_chat:
                        send_message(chat_id, "❌ Эта команда доступна только в админ-чате.")
                        continue
                    if not has_permission(user_id, 'admin'):
                        send_message(chat_id, "❌ У вас нет прав на выполнение этой команды.")
                        continue
                    
                    # Формируем информацию с использованием эмодзи и разделителей
                    info_parts = [
                        "📊 ИНФОРМАЦИЯ О НАСТРОЙКАХ",
                        "",
                        f"⏱️ Интервал между рассылками: *{cd_min}* минут",
                        f"⚡ Интервал отправки сообщений: *{interval_sec}* секунд",
                        "",
                        "📝 ТЕКСТ РАССЫЛКИ:",
                        "" if not message_text.strip() else message_text,
                        ""
                    ]
                    
                    # Добавляем дополнительные тексты, если есть
                    if additional_texts:
                        info_parts.append("📎 ДОПОЛНИТЕЛЬНЫЕ ТЕКСТЫ:")
                        for i, add_text in enumerate(additional_texts, 1):
                            if add_text.strip():
                                info_parts.append(f"{i}. {add_text.strip()}")
                        info_parts.append("")
                    
                    # Формируем итоговое сообщение
                    info_message = '\n'.join(info_parts)
                    send_message(chat_id, info_message)
                    update_user_stats(user_id, 'command')
                elif text == '.допсписок':
                    if chat_id != admin_chat:
                        send_message(chat_id, "❌ Эта команда доступна только в админ-чате.")
                        continue
                    if not has_permission(user_id, 'admin'):
                        send_message(chat_id, "❌ У вас нет прав на выполнение этой команды.")
                        continue
                    current_texts = [text for text in additional_texts if text.strip()]
                    if not current_texts:
                        send_message(chat_id, "Дополнительных текстов пока нет.")
                    else:
                        text_list = "\n".join(f"#{i+1}: {text}" for i, text in enumerate(current_texts))
                        send_message(chat_id, f"Список дополнительных текстов:\n{text_list}")
                    update_user_stats(user_id, 'command')

                elif text == '.пинг':
                    if chat_id != admin_chat:
                        send_message(chat_id, "❌ Эта команда доступна только в админ-чате.")
                        continue
                    start_time = time.time()
                    msg = send_message(chat_id, 'Проверка пинга...')
                    end_time = time.time()
                    ping_time = int((end_time - start_time) * 1000)
                    send_message(chat_id, f'Пинг: {ping_time}ms')
                    update_user_stats(user_id, 'command')

                elif text == '.хелп':
                    if chat_id != admin_chat:
                        send_message(chat_id, "❌ Эта команда доступна только в админ-чате.")
                        continue
                    role = get_role(user_id)
                    help_text = get_help_text(role)
                    send_message(chat_id, help_text)
                    update_user_stats(user_id, 'command')

                # === ДОБАВЬТЕ НОВУЮ КОМАНДУ .настройки ===

                elif text.startswith('.настройки'):
                    if chat_id != admin_chat:
                        send_message(chat_id, "❌ Эта команда доступна только в админ-чате.")
                        continue
                    if not has_permission(user_id, 'dev'):
                        send_message(chat_id, "❌ У вас нет прав на выполнение этой команды.")
                        continue
                    try:
                        args = text.split()
                        if len(args) != 3:
                            send_message(chat_id, "❌ Неверный формат. Используйте: .настройки [cd_min|interval_sec] [число]")
                            continue
                        key = args[1]
                        value = float(args[2])
                        if key == 'cd_min':
                            if value < 1 or value > 1440:
                                send_message(chat_id, "❌ КД должно быть от 1 до 1440 минут.")
                                continue
                            cd_min = int(value)
                            # Обновляем config.py
                            with open('config.py', 'r', encoding='utf-8') as f:
                                config_lines = f.readlines()
                            with open('config.py', 'w', encoding='utf-8') as f:
                                for line in config_lines:
                                    if line.startswith('cd_min ='):
                                        f.write(f'cd_min = {cd_min}\n')
                                    else:
                                        f.write(line)
                            send_message(chat_id, f"✅ Установлено: cd_min = {cd_min} мин")
                        elif key == 'interval_sec':
                            if value < 0.01 or value > 60:
                                send_message(chat_id, "❌ Интервал должен быть от 0.01 до 60 секунд.")
                                continue
                            interval_sec = value
                            # Обновляем config.py
                            with open('config.py', 'r', encoding='utf-8') as f:
                                config_lines = f.readlines()
                            with open('config.py', 'w', encoding='utf-8') as f:
                                for line in config_lines:
                                    if line.startswith('interval_sec ='):
                                        f.write(f'interval_sec = {interval_sec}\n')
                                    else:
                                        f.write(line)
                            send_message(chat_id, f"✅ Установлено: interval_sec = {interval_sec} сек")
                        else:
                            send_message(chat_id, "❌ Неизвестный параметр. Доступно: cd_min, interval_sec")
                    except Exception as e:
                        send_message(chat_id, f"❌ Ошибка: {e}")
                elif text.startswith('.добтекст'):
                    if chat_id != admin_chat:
                        send_message(chat_id, "❌ Эта команда доступна только в админ-чате.")
                        continue
                    if not has_permission(user_id, 'admin'):
                        send_message(chat_id, "❌ У вас нет прав на выполнение этой команды.")
                        continue
                    try:
                        new_text = text.split(' ', 1)[1]
                        if new_text not in additional_texts:
                            additional_texts.append(new_text)
                            save_data()
                            send_message(chat_id, f"{new_text}")
                    except IndexError:
                        send_message(chat_id, "Неверный формат команды. Используйте: .добтекст [текст]")
                    update_user_stats(user_id, 'command')
                elif text.startswith('.удтекст'):
                    if chat_id != admin_chat:
                        send_message(chat_id, "❌ Эта команда доступна только в админ-чате.")
                        continue
                    if not has_permission(user_id, 'admin'):
                        send_message(chat_id, "❌ У вас нет прав на выполнение этой команды.")
                        continue
                    try:
                        args = text.split(' ', 1)
                        if len(args) < 2:
                            send_message(chat_id, "Укажите номер текста для удаления. Пример: .удтекст 1")
                            continue
                        text_number = int(args[1])
                        if text_number < 1:
                            send_message(chat_id, "Номер должен быть положительным числом.")
                            continue
                        # Проверяем количество доступных текстов
                        available_count = len(additional_texts)
                        if available_count == 0:
                            send_message(chat_id, "Список дополнительных текстов пуст.")
                            continue
                        if text_number > available_count:
                            send_message(chat_id, f"Неверный номер текста. Доступны номера от 1 до {available_count}.")
                            continue
                        # Удаляем текст по номеру (преобразуем номер в индекс)
                        idx = text_number - 1
                        removed_text = additional_texts.pop(idx)
                        # Удаляем фото, если они были
                        if str(idx) in additional_photos_by_text:
                            del additional_photos_by_text[str(idx)]
                        save_data()
                        send_message(chat_id, f"Дополнительный текст #{text_number} удалён: {removed_text}")
                    except ValueError:
                        send_message(chat_id, "Номер должен быть числом. Пример: .удтекст 1")
                    except IndexError:
                        send_message(chat_id, "Укажите номер текста для удаления. Пример: .удтекст 1")
                    update_user_stats(user_id, 'command')
                
                # --- Команда .добид ---
                elif text.startswith('.добид'):
                    if chat_id != admin_chat:
                        send_message(chat_id, "❌ Эта команда доступна только в админ-чате.")
                        continue
                    if not has_permission(user_id, 'admin'):
                        send_message(chat_id, "❌ У вас нет прав на выполнение этой команды.")
                        continue
                    try:
                        args = text.split(' ', 1)
                        if len(args) < 2:
                            send_message(chat_id, "❌ Укажите количество чатов. Пример: .добид 100")
                            continue
                        count = int(args[1])
                        if count <= 0:
                            send_message(chat_id, "❌ Количество должно быть положительным числом.")
                            continue
                        if count > 10000:
                            send_message(chat_id, "❌ Максимальное количество — 10000 чатов за раз.")
                            continue
                        
                        # Фильтруем только ID бот-чатов (начинающиеся с 2)
                        bot_chat_ids = [cid for cid in chat_ids if str(cid).startswith('2') and len(str(cid)) == 10]
                        start_id = 2000000001
                        if bot_chat_ids:
                            start_id = max(bot_chat_ids) + 1
                        
                        new_ids = []
                        for i in range(count):
                            new_id = start_id + i
                            if new_id not in chat_ids:
                                new_ids.append(new_id)
                        
                        chat_ids.extend(new_ids)
                        save_data()
                        if new_ids:
                            send_message(chat_id, f"✅ Добавлено {len(new_ids)} чатов: от {new_ids[0]} до {new_ids[-1]}")
                        else:
                            send_message(chat_id, "✅ Все запрошенные ID уже существуют.")
                    except ValueError:
                        send_message(chat_id, "❌ Количество должно быть числом.")
                    except Exception as e:
                        send_message(chat_id, "❌ Ошибка при добавлении чатов.")
                        print(f"[ERROR] Ошибка при выполнении .добид: {e}")
                    update_user_stats(user_id, 'command')

                # --- Команда .делид ---
                elif text.startswith('.делид'):
                    if chat_id != admin_chat:
                        send_message(chat_id, "❌ Эта команда доступна только в админ-чате.")
                        continue
                    if not has_permission(user_id, 'admin'):
                        send_message(chat_id, "❌ У вас нет прав на выполнение этой команды.")
                        continue
                    try:
                        args = text.split(' ', 1)
                        if len(args) < 2:
                            send_message(chat_id, "❌ Укажите количество чатов для удаления. Пример: .делид 10")
                            continue
                        count = int(args[1])
                        if count <= 0:
                            send_message(chat_id, "❌ Количество должно быть положительным числом.")
                            continue
                        
                        # Фильтруем только ID бот-чатов
                        bot_chat_ids = [cid for cid in chat_ids if str(cid).startswith('2') and len(str(cid)) == 10]
                        # Удаляем с конца
                        removed_count = 0
                        for _ in range(min(count, len(bot_chat_ids))):
                            if bot_chat_ids:
                                chat_to_remove = bot_chat_ids.pop()
                                if chat_to_remove in chat_ids:
                                    chat_ids.remove(chat_to_remove)
                                    removed_count += 1
                        
                        save_data()
                        send_message(chat_id, f"✅ Удалено {removed_count} чатов с конца списка.")
                    except ValueError:
                        send_message(chat_id, "❌ Количество должно быть числом.")
                    except Exception as e:
                        send_message(chat_id, "❌ Ошибка при удалении чатов.")
                        print(f"[ERROR] Ошибка при выполнении .делид: {e}")
                    update_user_stats(user_id, 'command')
                elif text == '.админчат':
                    if not has_permission(user_id, 'dev'):
                        send_message(chat_id, "❌ У вас нет прав на выполнение этой команды.")
                        continue
                    if admin_chat == chat_id:
                        send_message(chat_id, "⚠️ Этот чат уже является административным.")
                    else:
                        admin_chat = chat_id
                        save_data()
                        send_message(chat_id, "Административный чат установлен.")

                elif text == '.уст':
                    # Команда .уст доступна только в админ-чате
                    if admin_chat is None:
                        send_message(chat_id, "Администратор не установлен.")
                    elif admin_chat != chat_id:
                        send_message(chat_id, "❌ Эта команда доступна только из административного чата.")
                    else:
                        if not has_permission(user_id, 'admin'):
                            send_message(chat_id, "❌ У вас нет прав на выполнение этой команды.")
                            continue
                        if len(str(chat_id)) == 10 and str(chat_id).startswith('2'):
                            if chat_id not in chat_ids:
                                chat_ids.append(chat_id)
                                save_data()
                                send_message(chat_id, "Этот чат добавлен в список для рассылки сообщений.")
                            else:
                                send_message(chat_id, "❌ Этот чат уже в списке рассылки.")
                        else:
                            send_message(chat_id, "Невозможно добавить этот чат: это не беседа.")
                elif text.startswith('.') and text.split()[0] == '.добфото':
                    if chat_id != admin_chat:
                        send_message(chat_id, "❌ Эта команда доступна только в админ-чате.")
                        continue
                    if not has_permission(user_id, 'admin'):
                        send_message(chat_id, "❌ У вас нет прав на выполнение этой команды.")
                        continue
                    try:
                        args = text.split(' ', 1)
                        if len(args) < 2:
                            send_message(chat_id, "Укажите номер текста. Пример: .добфото 1")
                            continue
                        text_number = int(args[1])
                        if text_number < 1:
                            send_message(chat_id, "Номер должен быть положительным числом.")
                            continue
                        text_idx = text_number - 1
                        if text_idx >= len(additional_texts) or text_idx < 0:
                            send_message(chat_id, f"Текст с номером {text_number} не существует.")
                            continue
                        
                        # Проверяем вложения в текущем сообщении
                        if 'attachments' not in message or not message['attachments']:
                            send_message(chat_id, "❌ Прикрепите фото к сообщению с командой .добфото")
                            continue
                            
                        photos = []
                        for att in message['attachments']:
                            if att['type'] == 'photo':
                                max_size = max(att['photo']['sizes'], key=lambda x: x['width'] * x['height'])
                                photo_url = max_size['url']
                                photo_response = requests.get(photo_url)
                                if photo_response.status_code == 200:
                                    uploaded = upload_photo_to_vk_from_memory(photo_response.content)
                                    if uploaded:
                                        photos.append(uploaded)
                        
                        if photos:
                            idx_str = str(text_idx)
                            if idx_str not in additional_photos_by_text:
                                additional_photos_by_text[idx_str] = []
                            additional_photos_by_text[idx_str].extend(photos)
                            save_data()
                            attachment_str = ','.join(photos)
                            send_message(chat_id, f"✅ Фото успешно добавлены к доп. тексту №{text_number}", attachment=attachment_str)
                            update_user_stats(user_id, 'osn_photo')
                        else:
                            send_message(chat_id, "❌ Не удалось обработать ни одно фото.")
                    except ValueError:
                        send_message(chat_id, "Номер должен быть числом. Пример: .добфото 1")
                    except Exception as e:
                        send_message(chat_id, f"Произошла ошибка при обработке команды: {str(e)}")
                elif text.startswith('.') and text.split()[0] == '.удфото':
                    if chat_id != admin_chat:
                        send_message(chat_id, "❌ Эта команда доступна только в админ-чате.")
                        continue
                    if not has_permission(user_id, 'admin'):
                        send_message(chat_id, "❌ У вас нет прав на выполнение этой команды.")
                        continue
                    try:
                        args = text.split(' ', 1)
                        if len(args) < 2:
                            send_message(chat_id, "Укажите номер текста. Пример: .удфото 1")
                            continue
                        text_number = int(args[1])
                        if text_number < 1:
                            send_message(chat_id, "Номер должен быть положительным числом.")
                            continue
                        text_idx = text_number - 1
                        if text_idx >= len(additional_texts) or text_idx < 0:
                            send_message(chat_id, f"Текст с номером {text_number} не существует.")
                            continue
                        idx_str = str(text_idx)
                        if idx_str in additional_photos_by_text:
                            del additional_photos_by_text[idx_str]
                            save_data()
                            send_message(chat_id, f"🗑️ Все фото для доп. текста №{text_number} удалены")
                        else:
                            send_message(chat_id, f"ℹ️ У доп. текста №{text_number} не было прикреплённых фото")
                    except ValueError:
                        send_message(chat_id, "Номер должен быть числом. Пример: .удфото 1")
                # Проверка фото от пользователей, ожидающих добавления
                elif 'attachments' in message and message['attachments'] and user_id in photo_wait_queue:
                    wait_data = photo_wait_queue[user_id]
                    if time.time() > wait_data['expires']:
                        del photo_wait_queue[user_id]
                        send_message(chat_id, "⏳ Время ожидания фото истекло. Отменено.")
                    else:
                        photos = []
                        for att in message['attachments']:
                            if att['type'] == 'photo':
                                max_size = max(att['photo']['sizes'], key=lambda x: x['width'] * x['height'])
                                photo_url = max_size['url']
                                photo_response = requests.get(photo_url)
                                if photo_response.status_code == 200:
                                    uploaded = upload_photo_to_vk_from_memory(photo_response.content)
                                    if uploaded:
                                        photos.append(uploaded)
                        if photos:
                            text_idx = wait_data['text_idx']
                            if text_idx not in additional_photos_by_text:
                                additional_photos_by_text[text_idx] = []
                            additional_photos_by_text[text_idx].extend(photos)
                            save_data()
                            attachment_str = ','.join(photos)
                            send_message(chat_id, f"✅ Фото успешно добавлены к доп. тексту №{int(text_idx) + 1}", attachment=attachment_str)
                        else:
                            send_message(chat_id, "❌ Не удалось обработать ни одно фото.")
                        del photo_wait_queue[user_id]
    except Exception as e:
        print(f'[!] Произошла ошибка: {e}')
        time.sleep(5)