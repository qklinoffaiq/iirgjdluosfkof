import vk_api
from vk_api.bot_longpoll import VkBotLongPoll, VkBotEventType
import time
import threading
import json
import os
import requests
from config import MESSAGE_CONFIG, admin_ids, main_photo

from config import group_token
from config import group_id
cd_min = 10  # Минимальное время между сообщениями в минутах
interval_sec = 0.01  # Интервал между сообщениями в секундах
additional_texts = []  # Дополнительные тексты
additional_texts_separator = "\n\n"  # Разделитель для дополнительных текстов
additional_photos_by_text = {}  # Словарь для хранения вложений по текстам
photo_wait_queue = {}           # Очередь ожидания фото от пользователей
pending_delid_requests = {}      # Очередь ожидания для команды .делид
pending_dobid_requests = {}      # Очередь ожидания для команды .добид

# Загружаем основное фото из конфига
# main_photo определяется в импортированных переменных выше

data_file = 'data.json'

try:
    message_text = MESSAGE_CONFIG['text']
    chat_ids = MESSAGE_CONFIG['chat_ids'][:]
    admin_chat = MESSAGE_CONFIG['admin_chat']
except Exception as e:
    print(f"[!] Ошибка загрузки конфигурации: {e}")
    message_text = "Текст для рассылки"
    chat_ids = []
    admin_chat = None


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

reset_event = threading.Event()

def save_data():
    # Исключаем admin_chat из списка, если он там есть
    if admin_chat in chat_ids:
        chat_ids.remove(admin_chat)
    with open(data_file, 'w', encoding='utf-8') as f:
        json.dump({'message_text': message_text, 'chat_ids': chat_ids, 'admin_chat': admin_chat, 'additional_photos_by_text': additional_photos_by_text}, f, ensure_ascii=False, indent=4)

def send_message(chat_id, text, attachment=None):
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
        current_chat_ids = chat_ids.copy()
        
        for chat_id in current_chat_ids:
            if admin_chat is not None and chat_id != admin_chat:
                if len(str(chat_id)) == 10 and str(chat_id).startswith('2'):
                    
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
                                    break
                                
                                time.sleep(interval_sec)
                    
                    # Отправка основного сообщения
                    result = send_message(chat_id, message_text, attachment=uploaded_photo)
                    
                    # Проверяем, нужно ли остановить рассылку после основного сообщения
                    if result == 'access_error':
                        print("[INFO] Рассылка остановлена из-за ошибки доступа.")
                        break
                    
                else:
                    print(f"[WARNING] Chat {chat_id}: Некорректный ID чата. Пропущено.")


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
                # Проверяем, является ли отправитель администратором по его user_id
                # Пропускаем проверку только для команды .админ
                if user_id not in admin_ids:
                    if text.startswith('.'):
                        if not text.startswith('.админ'):
                            send_message(chat_id, "❌ Использование команд бота разрешено только администраторам.")
                            print(f"Попытка использования команды пользователем {user_id}, который не в списке администраторов")
                            continue

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
                    if user_id not in admin_ids:
                        send_message(chat_id, "❌ Использование команды .редтекст разрешено только администраторам.")
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
                        # Проверяем наличие вложений в сообщении
                        if 'attachments' in message and message['attachments']:
                            attachment = message['attachments'][0]
                            if attachment['type'] == 'photo':
                                # Получаем фото с максимальным качеством
                                sizes = attachment['photo']['sizes']
                                max_size = max(sizes, key=lambda x: x['width'] * x['height'])
                                photo_id = max_size['url']
                                if str(idx) not in additional_photos_by_text:
                                    additional_photos_by_text[str(idx)] = []
                                # Очищаем старые фото и добавляем новое
                                additional_photos_by_text[str(idx)] = [f"photo{attachment['photo']['owner_id']}_{attachment['photo']['id']}"]
                        save_data()
                        # Отправляем только ОДНО сообщение с вложением
                        attachments = additional_photos_by_text.get(str(idx), [])
                        send_message(chat_id, f"{new_text}", attachment=','.join(attachments) if attachments else None)
                    except Exception as e:
                        send_message(chat_id, "Ошибка при обработке команды.")
                elif text == '.список':
                    if chat_id != admin_chat:
                        send_message(chat_id, "❌ Эта команда доступна только в админ-чате.")
                        continue
                    total_chats = len(chat_ids)
                    chat_list = "\n".join(str(cid) for cid in chat_ids if cid != admin_chat)
                    send_message(chat_id, f"Количество чатов для рассылки: {total_chats}\nСписок чатов:\n{chat_list}")
                elif text == '.рассылка':
                    if chat_id != admin_chat:
                        send_message(chat_id, "❌ Эта команда доступна только в админ-чате.")
                        continue
                    if admin_chat:
                        if reset_event.is_set():
                            reset_event.clear()
                        reset_event.set()
                        send_message(admin_chat, "Рассылка запущена и таймер сброшен.")
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
                elif text.startswith('.редоснтекст'):
                    if chat_id != admin_chat:
                        send_message(chat_id, "❌ Эта команда доступна только в админ-чате.")
                        continue
                    if user_id not in admin_ids:
                        send_message(chat_id, "❌ Использование команды .редоснтекст разрешено только администраторам.")
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
                                main_photo = max_size['url']
                        
                        save_data()
                        # Отправляем только ОДНО сообщение с вложением
                        send_message(chat_id, new_main_text, attachment=uploaded_photo)
                    except (IndexError, ValueError):
                        send_message(chat_id, "Неверный формат команды. Используйте: .редоснтекст [текст]")
                elif text == '.ид':
                    if chat_id != admin_chat:
                        send_message(chat_id, "❌ Эта команда доступна только в админ-чате.")
                        continue
                    send_message(chat_id, f"✅ ID этой беседы: {chat_id}")
                elif text == '.инфо':
                    if chat_id != admin_chat:
                        send_message(chat_id, "❌ Эта команда доступна только в админ-чате.")
                        continue
                    additional_text_display = "" if not additional_texts else additional_texts_separator.join(additional_texts).strip()
                    send_message(chat_id, f"🔸 Настройки:\n\nКД между сообщениями: {cd_min} минут.\nИнтервал рассылки: {interval_sec} секунд.\nТекст рассылки:\n\n{message_text}\nДополнительное сообщение:\n\n{additional_text_display}")
                elif text == '.допсписок':
                    if chat_id != admin_chat:
                        send_message(chat_id, "❌ Эта команда доступна только в админ-чате.")
                        continue
                    current_texts = [text for text in additional_texts if text.strip()]
                    if not current_texts:
                        send_message(chat_id, "Дополнительных текстов пока нет.")
                    else:
                        text_list = "\n".join(f"#{i+1}: {text}" for i, text in enumerate(current_texts))
                        send_message(chat_id, f"Список дополнительных текстов:\n{text_list}")
                elif text == '.хелп':
                    if chat_id != admin_chat:
                        send_message(chat_id, "❌ Эта команда доступна только в админ-чате.")
                        continue
                    help_text = (
                        "📋 Доступные команды:\n"
                        "\n"
                        "🔹 .редтекст [номер] [текст] — редактировать дополнительный текст под номером\n"
                        "🔹 .допсписок — показать все дополнительные тексты\n"
                        "🔹 .добтекст [текст] — добавить дополнительный текст\n"
                        "🔹 .удтекст [номер] — удалить дополнительный текст по номеру\n"
                        "🔹 .рассылка — запустить рассылку\n"
                        "🔹 .список — показать количество чатов\n"
                        "🔹 .ид — узнать ID текущего чата\n"
                        "🔹 .инфо — показать текущие настройки\n"
                        "🔹 .пинг — проверить, работает ли бот\n"
                        "🔹 .хелп — показать это сообщение\n"
                        "🔹 .админ — установить текущий чат как административный\n"
                        "🔹 .уст — добавить текущий чат в список рассылки\n"
                        "🔹 .инфочат — получить информацию о чате\n"
                        "🔹 .добид [ID] — добавить чат в список по ID\n"
                        "🔹 .делид [ID] — удалить чат из списка по ID\n"
                        "🔹 .тест — отправить тестовое сообщение в текущий чат\n"
                        "🔹 .редоснтекст [текст] — редактировать основной текст рассылки (только для разработчика)\n"
                        "🔹 .добфото [номер] — добавить фото к дополнительному тексту\n"
                        "🔹 .удфото [номер] — удалить все фото у дополнительного текста\n"
                    )
                    send_message(chat_id, help_text)
                elif text == '.пинг':
                    if chat_id != admin_chat:
                        send_message(chat_id, "❌ Эта команда доступна только в админ-чате.")
                        continue
                    start_time = time.time()
                    msg = send_message(chat_id, 'Проверка пинга...')
                    end_time = time.time()
                    ping_time = int((end_time - start_time) * 1000)
                    send_message(chat_id, f'Пинг: {ping_time}ms')
                elif text.startswith('.добтекст'):
                    if chat_id != admin_chat:
                        send_message(chat_id, "❌ Эта команда доступна только в админ-чате.")
                        continue
                    if user_id not in admin_ids:
                        send_message(chat_id, "❌ Использование команды .добтекст разрешено только администраторам.")
                        continue
                    try:
                        new_text = text.split(' ', 1)[1]
                        if new_text not in additional_texts:
                            additional_texts.append(new_text)
                            # Проверяем наличие фотографии в сообщении
                            if 'attachments' in message and message['attachments']:
                                attachment = message['attachments'][0]
                                if attachment['type'] == 'photo':
                                    # Получаем фото с максимальным качеством
                                    sizes = attachment['photo']['sizes']
                                    max_size = max(sizes, key=lambda x: x['width'] * x['height'])
                                    photo_id = f"photo{attachment['photo']['owner_id']}_{attachment['photo']['id']}"
                                    text_idx = str(len(additional_texts) - 1)
                                    if text_idx not in additional_photos_by_text:
                                        additional_photos_by_text[text_idx] = []
                                    additional_photos_by_text[text_idx].append(photo_id)
                            save_data()
                            # Отправляем сообщение с вложением, если оно есть
                            idx_str = str(len(additional_texts) - 1)
                            attachments = additional_photos_by_text.get(idx_str, [])
                            send_message(chat_id, f"{new_text}", attachment=','.join(attachments) if attachments else None)
                    except IndexError:
                        send_message(chat_id, "Неверный формат команды. Используйте: .добтекст [текст]")
                elif text.startswith('.удтекст'):
                    if chat_id != admin_chat:
                        send_message(chat_id, "❌ Эта команда доступна только в админ-чате.")
                        continue
                    if user_id not in admin_ids:
                        
                        send_message(chat_id, "❌ Использование команды .удтекст разрешено только администраторам.")
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
                
                elif text == '.делид':
                    if chat_id != admin_chat:
                        send_message(chat_id, "❌ Команда доступна только в админ-чате.")
                        continue
                    if user_id not in admin_ids:
                        send_message(chat_id, "❌ Использование команды .делид разрешено только администраторам.")
                        continue
                    if chat_id in pending_delid_requests:
                        send_message(chat_id, "🕒 Вы уже начали команду .делид. Пожалуйста, завершите её.")
                        continue
                    # Активируем ожидание количества
                    pending_delid_requests[chat_id] = {'step': 'waiting_count', 'admin_id': user_id}
                    send_message(chat_id, "🔢 Сколько чатов вы хотите удалить с конца списка? Пожалуйста, введите число.")

                # Обработка ввода количества для команды .делид
                elif chat_id in pending_delid_requests and pending_delid_requests[chat_id]['step'] == 'waiting_count':
                    if user_id != pending_delid_requests[chat_id]['admin_id']:
                        send_message(chat_id, "❌ Эта команда была начата другим администратором.")
                        continue
                    try:
                        count = int(text.strip())
                        if count <= 0:
                            send_message(chat_id, "❌ Ошибка: введите положительное число.")
                            continue
                        
                        # Фильтруем только ID бот-чатов из глобального списка
                        bot_chat_ids = [cid for cid in chat_ids if str(cid).startswith('2000000')]
                        
                        if count > len(bot_chat_ids):
                            send_message(chat_id, f"❌ Невозможно удалить {count} чатов. В списке только {len(bot_chat_ids)} чатов.")
                            continue
                        
                        # Получаем последние N чатов с конца списка
                        ids_to_remove = bot_chat_ids[-count:]
                        
                        # Удаляем из глобального списка
                        for cid in ids_to_remove:
                            if cid in chat_ids:
                                chat_ids.remove(cid)
                        
                        save_data()
                        
                        send_message(chat_id, f"✅ Успешно удалено {len(ids_to_remove)} чатов с конца списка.")
                    except ValueError:
                        send_message(chat_id, "❌ Ошибка: введите корректное число.")
                    finally:
                        # Завершаем сессию
                        if chat_id in pending_delid_requests:
                            del pending_delid_requests[chat_id]

                elif text == '.добид':
                    if chat_id != admin_chat:
                        send_message(chat_id, "❌ Команда доступна только в админ-чате.")
                        continue
                    if user_id not in admin_ids:
                        send_message(chat_id, "❌ Использование команды .добид разрешено только администраторам.")
                        continue
                    if chat_id in pending_dobid_requests:
                        send_message(chat_id, "🕒 Вы уже начали команду .добид. Пожалуйста, завершите её.")
                        continue
                    # Активируем ожидание числа
                    pending_dobid_requests[chat_id] = {'step': 'waiting_count', 'admin_id': user_id}
                    send_message(chat_id, "🔢 Сколько чатов вы хотите добавить? Пожалуйста, введите число.")

                # Обработка ввода числа для команды .добид
                elif chat_id in pending_dobid_requests and pending_dobid_requests[chat_id]['step'] == 'waiting_count':
                    if user_id != pending_dobid_requests[chat_id]['admin_id']:
                        send_message(chat_id, "❌ Эта команда была начата другим администратором.")
                        continue
                    try:
                        n = int(text.strip())
                        if n <= 0:
                            send_message(chat_id, "❌ Ошибка: введите положительное число.")
                            continue
                        if n > 10000:
                            send_message(chat_id, "⚠️ Максимальное количество за раз — 10000.")
                            continue
                        # Используем только последнее значение из chat_ids как базу
                        if chat_ids:
                            # Фильтруем только ID бот-чатов (начинающиеся с 2000000)
                            bot_chat_ids = [cid for cid in chat_ids if str(cid).startswith('2000000')]
                            if bot_chat_ids:
                                last_id = max(bot_chat_ids)
                                start_id = last_id + 1
                            else:
                                start_id = 2000000001
                        else:
                            start_id = 2000000001
                        
                        new_ids = []
                        for i in range(n):
                            new_id = start_id + i
                            # Проверяем, что ID не существует в текущем списке
                            if new_id not in chat_ids:
                                new_ids.append(new_id)
                        # Обновляем глобальные chat_ids
                        chat_ids.extend(new_ids)
                        save_data()
                        if new_ids:
                            send_message(chat_id, f"✅ Успешно добавлено {len(new_ids)} чатов: от {new_ids[0]} до {new_ids[-1]}")
                        else:
                            send_message(chat_id, "✅ Все запрошенные ID уже существуют.")
                    except ValueError:
                        send_message(chat_id, "❌ Ошибка: введите корректное число.")
                    finally:
                        # Завершаем сессию
                        if chat_id in pending_dobid_requests:
                            del pending_dobid_requests[chat_id]
                elif text == '.админ':
                    if user_id in admin_ids:
                        if admin_chat == chat_id:
                            send_message(chat_id, "⚠️ Этот чат уже является административным.")
                        else:
                            admin_chat = chat_id
                            save_data()
                            send_message(chat_id, "Административный чат установлен.")
                    else:
                        send_message(chat_id, "❌ Установка админ-чата разрешена только администраторам.")

                elif text == '.уст':
                    # Команда .уст доступна только в админ-чате
                    if admin_chat is None:
                        send_message(chat_id, "Администратор не установлен.")
                    elif admin_chat != chat_id:
                        send_message(chat_id, "❌ Эта команда доступна только из административного чата.")
                    else:
                        if len(str(chat_id)) == 10 and str(chat_id).startswith('2'):
                            if chat_id not in chat_ids:
                                chat_ids.append(chat_id)
                                save_data()
                                send_message(chat_id, "Этот чат добавлен в список для рассылки сообщений.")
                            else:
                                send_message(chat_id, "❌ Этот чат уже в списке рассылки.")
                        else:
                            send_message(chat_id, "Невозможно добавить этот чат: это не беседа.")
                elif text.startswith('.добфото '):
                    if chat_id != admin_chat:
                        send_message(chat_id, "❌ Эта команда доступна только в админ-чате.")
                        continue
                    if user_id not in admin_ids:
                        send_message(chat_id, "❌ Использование команды .добфото разрешено только администраторам.")
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
                        # Переводим пользователя в режим ожидания фото
                        photo_wait_queue[user_id] = {
                            'text_idx': str(text_idx),
                            'expires': time.time() + 60
                        }
                        send_message(chat_id, f"📸 Пожалуйста, отправьте одно или несколько фото для доп. текста №{text_number}")
                    except ValueError:
                        send_message(chat_id, "Номер должен быть числом. Пример: .добфото 1")
                elif text.startswith('.удфото '):
                    if chat_id != admin_chat:
                        send_message(chat_id, "❌ Эта команда доступна только в админ-чате.")
                        continue
                    if user_id not in admin_ids:
                        send_message(chat_id, "❌ Использование команды .удфото разрешено только администраторам.")
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
                elif user_id in photo_wait_queue:
                    wait_data = photo_wait_queue[user_id]
                    if time.time() > wait_data['expires']:
                        del photo_wait_queue[user_id]
                        send_message(chat_id, "⏳ Время ожидания фото истекло. Отменено.")
                    else:
                        if 'attachments' in message and message['attachments']:
                            photos = []
                            # Храним фото в памяти как байты
                            for att in message['attachments']:
                                if att['type'] == 'photo':
                                    # Берем фото максимального размера
                                    max_size = max(att['photo']['sizes'], key=lambda x: x['width'] * x['height'])
                                    photo_url = max_size['url']
                                    
                                    # Скачиваем фото в память
                                    photo_response = requests.get(photo_url)
                                    if photo_response.status_code == 200:
                                        # Загружаем фото напрямую из памяти
                                        uploaded = upload_photo_to_vk_from_memory(photo_response.content)
                                        if uploaded:
                                            photos.append(uploaded)
                                    
                            if photos:
                                text_idx = wait_data['text_idx']
                                if text_idx not in additional_photos_by_text:
                                    additional_photos_by_text[text_idx] = []
                                additional_photos_by_text[text_idx].extend(photos)
                                save_data()
                                # Отправляем подтверждение с вложением
                                attachment_str = ','.join(photos)
                                send_message(chat_id, f"✅ Фото успешно добавлены к доп. тексту №{int(text_idx) + 1}", attachment=attachment_str)
                            else:
                                send_message(chat_id, "Не удалось загрузить фото. Попробуйте еще раз.")
                        # Удаляем из очереди в любом случае после обработки
                        del photo_wait_queue[user_id]
    except Exception as e:
        print(f'[!] Произошла ошибка: {e}')
        time.sleep(5)