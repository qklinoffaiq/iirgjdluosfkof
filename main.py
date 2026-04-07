import vk_api
from vk_api.bot_longpoll import VkBotLongPoll, VkBotEventType
import time
import threading
import json
import os
from config import group_token, group_id, cd_min, interval_sec, additional_texts, admin_ids, additional_texts_separator

data_file = 'data.json'

if os.path.exists(data_file):
    with open(data_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
        message_text = data.get('message_text', "Текст для рассылки")
        chat_ids = data.get('chat_ids', [])
    admin_chat = data.get('admin_chat', None)
else:
    message_text = "Текст для рассылки"
    chat_ids = []
    admin_chat = None


vk_session = vk_api.VkApi(token=group_token)
vk = vk_session.get_api()

# Попытка создать Long Poll, но игнорировать ошибку, если Long Poll не включен
try:
    longpoll = VkBotLongPoll(vk_session, group_id)
    longpoll_enabled = True
except vk_api.exceptions.ApiError as e:
    print(f"[!] Ошибка инициализации Long Poll: {e}. Возможно, в настройках группы не включен Long Poll API.")
    longpoll_enabled = False

reset_event = threading.Event()

def save_data():
    # Исключаем admin_chat из списка, если он там есть
    if admin_chat in chat_ids:
        chat_ids.remove(admin_chat)
    with open(data_file, 'w', encoding='utf-8') as f:
        json.dump({'message_text': message_text, 'chat_ids': chat_ids, 'admin_chat': admin_chat}, f, ensure_ascii=False, indent=4)

def send_message(chat_id, text):
    try:
        response = vk.messages.send(
            peer_id=chat_id,
            message=text,
            random_id=0
        )
        print(f"[+] Сообщение успешно отправлено в чат {chat_id}")
        return response
    except Exception as e:
        error_msg = str(e)
        if '[917]' in error_msg:
            print(f'\n[!] Ошибка доступа к чату {chat_id}. Сообщение НЕ отправлено, но чат сохранён.')
        else:
            print(f'\n[!] Произошла ошибка: {e}. Сообщение не отправлено, чат {chat_id} оставлен для повторной отправки.')
        return None


def broadcast_message():
    while True:
        reset_event.wait(timeout=cd_min * 60)
        reset_event.clear()
        for chat_id in chat_ids:
            if admin_chat is not None and chat_id != admin_chat:
                if len(str(chat_id)) == 10 and str(chat_id).startswith('2'):
                    try:
                        send_message(chat_id, message_text)
                        time.sleep(interval_sec)
                        if additional_texts:
                            add_text = additional_texts_separator.join(additional_texts).strip()
                            if add_text:
                                send_message(chat_id, add_text)
                                time.sleep(interval_sec)
                    except Exception as e:
                        error_msg = str(e)
                        if '[917]' in error_msg:
                            print(f'\n[!] Ошибка доступа к чату {chat_id}. Сообщение НЕ отправлено, но чат сохранён.')
                        else:
                            print(f'\n[!] Произошла ошибка: {e}. Сообщение не отправлено, чат {chat_id} оставлен для повторной отправки.')
                else:
                    print(f'\n[!] Предупреждение: ID {chat_id} не является беседой. Сообщение не отправлено.')


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
                    help_text = (
                        "📋 Информация о чате:\n"
                        "\n"
                        "🔹 ID чата: " + str(chat_id) + "\n"
                        "🔹 ID отправителя: " + str(user_id) + "\n"
                        "🔹 Режим Long Poll: " + ("Включён" if longpoll_enabled else "Отключён или не настроен") + "\n"
                        "🔹 Текущий административный чат: " + (str(admin_chat) if admin_chat else "Не установлен") + "\n"
                        "▫️ Версия бота: 1.0\n"
                    )
                    send_message(chat_id, help_text)

                elif text.startswith('.редтекст'):
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
                        save_data()
                        send_message(chat_id, f"Текст дополнительного сообщения #{idx + 1} установлен: {new_text}")
                    except Exception as e:
                        send_message(chat_id, "Ошибка при обработке команды.")
                elif text == '.список':
                    total_chats = len(chat_ids)
                    chat_list = "\n".join(str(cid) for cid in chat_ids if cid != admin_chat)
                    send_message(chat_id, f"Количество чатов для рассылки: {total_chats}\nСписок чатов:\n{chat_list}")
                elif text == '.рассылка':
                    if admin_chat:
                        if reset_event.is_set():
                            reset_event.clear()
                        reset_event.set()
                        send_message(admin_chat, "Рассылка запущена и таймер сброшен.")
                elif text == '.тест':
                    # Отправляем сообщение только в текущий чат
                    send_message(chat_id, message_text)
                    if additional_texts:
                        add_text = additional_texts_separator.join(additional_texts).strip()
                        if add_text:
                            send_message(chat_id, add_text)
                elif text.startswith('.редоснтекст'):
                    if user_id != 574393629:
                        send_message(chat_id, "❌ Использование команды .редоснтекст разрешено только разработчику.")
                        continue
                    try:
                        new_main_text = text.split(' ', 1)[1]
                        message_text = new_main_text
                        save_data()
                        send_message(chat_id, f"Основной текст рассылки изменён на:\n{new_main_text}")
                    except IndexError:
                        send_message(chat_id, "Неверный формат команды. Используйте: .редоснтекст [текст]")
                elif text == '.ид':
                    send_message(chat_id, f"✅ ID этой беседы: {chat_id}")
                elif text == '.инфо':
                    additional_text_display = "" if not additional_texts else additional_texts_separator.join(additional_texts).strip()
                    send_message(chat_id, f"🔸 Настройки:\n\nКД между сообщениями: {cd_min} минут.\nИнтервал рассылки: {interval_sec} секунд.\nТекст рассылки:\n\n{message_text}\nДополнительное сообщение:\n\n{additional_text_display}")
                elif text == '.допсписок':
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
                    if user_id not in admin_ids:
                        send_message(chat_id, "❌ Использование команды .добтекст разрешено только администраторам.")
                        continue
                    try:
                        new_text = text.split(' ', 1)[1]
                        if new_text not in additional_texts:
                            additional_texts.append(new_text)
                            save_data()
                            send_message(chat_id, f"Добавлен новый дополнительный текст: {new_text}")
                    except IndexError:
                        send_message(chat_id, "Неверный формат команды. Используйте: .добтекст [текст]")
                elif text.startswith('.удтекст'):
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
                        save_data()
                        send_message(chat_id, f"Дополнительный текст #{text_number} удалён: {removed_text}")
                    except ValueError:
                        send_message(chat_id, "Номер должен быть числом. Пример: .удтекст 1")
                    except IndexError:
                        send_message(chat_id, "Укажите номер текста для удаления. Пример: .удтекст 1")
                
                elif text.startswith('.делид '):
                    if chat_id != admin_chat:
                        send_message(chat_id, "❌ Команда доступна только в админ-чате.")
                    else:
                        try:
                            id_to_remove = int(text[len('.делид '):].strip())
                            if id_to_remove in chat_ids:
                                chat_ids.remove(id_to_remove)
                                save_data()
                                send_message(chat_id, f"Чат с ID {id_to_remove} удалён из списка.")
                            else:
                                send_message(chat_id, f"Чат с ID {id_to_remove} не найден в списке.")
                        except ValueError:
                            send_message(chat_id, "Неверный формат ID. Используйте: .делид [числовой ID]")
                elif text.startswith('.добид '):
                    try:
                        id_to_add = int(text[len('.добид '):].strip())
                        if id_to_add not in chat_ids:
                            if len(str(id_to_add)) == 10 and str(id_to_add).startswith('2'):
                                chat_ids.append(id_to_add)
                                save_data()
                                send_message(chat_id, f"Чат с ID {id_to_add} добавлен в список.")
                            else:
                                send_message(chat_id, "Неверный формат ID чата. ID должен быть 10-значным числом, начинающимся с '2'.")
                        else:
                            send_message(chat_id, f"Чат с ID {id_to_add} уже в списке.")
                    except ValueError:
                        send_message(chat_id, "Неверный формат ID. Используйте: .добид [числовой ID]")
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
    except Exception as e:
        print(f'[!] Произошла ошибка: {e}')
        time.sleep(5)
