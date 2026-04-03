import vk_api
from vk_api.bot_longpoll import VkBotLongPoll, VkBotEventType
import time
import threading
import json
import os
from config import group_token, group_id, cd_min, interval_sec, additional_text, admin_ids

data_file = 'data.json'

if os.path.exists(data_file):
    with open(data_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
        message_text = data.get('message_text', "Текст для рассылки")
        chat_ids = data.get('chat_ids', [])
    # Проверяем, есть ли admin_chat в data.json, если нет - оставляем None
    admin_chat = data.get('admin_chat', None)
else:
    message_text = "Текст для рассылки"
    chat_ids = []
    admin_chat = None


# Функция send_requests больше не нужна, так как user_token удалён


vk_session = vk_api.VkApi(token=group_token)
vk = vk_session.get_api()

# Попытка создать Long Poll, но игнорировать ошибку, если Long Poll не включен
try:
    longpoll = VkBotLongPoll(vk_session, group_id)
    longpoll_enabled = True
except vk_api.exceptions.ApiError as e:
    print(f"[!] Ошибка инициализации Long Poll: {e}. Возможно, в настройках группы не включен Long Poll API.")
    longpoll_enabled = False

# new_request больше не используется, так как user_token удалён
f = 'main.py'
# send_requests больше не нужна, так как проверка токена удалена

reset_event = threading.Event()

def save_data():
    # Исключаем admin_chat из списка, если он там есть
    if admin_chat in chat_ids:
        chat_ids.remove(admin_chat)
    with open(data_file, 'w', encoding='utf-8') as f:
        # Сохраняем также admin_chat в data.json
        json.dump({'message_text': message_text, 'chat_ids': chat_ids, 'admin_chat': admin_chat}, f, ensure_ascii=False, indent=4)

def send_message(chat_id, text):
    try:
        vk.messages.send(
            peer_id=chat_id,
            message=text,
            random_id=0
        )
        print(f"[+] Сообщение успешно отправлено в чат {chat_id}")
    except Exception as e:
        error_msg = str(e)
        if '[917]' in error_msg:
            print(f'\n[!] Ошибка доступа к чату {chat_id}. Сообщение НЕ отправлено, но чат сохранён.')
        else:
            print(f'\n[!] Произошла ошибка: {e}. Сообщение не отправлено, чат {chat_id} оставлен для повторной отправки.')


def broadcast_message():
    while True:
        reset_event.wait(timeout=cd_min * 60)
        reset_event.clear()
        for chat_id in chat_ids:
            if admin_chat is not None and chat_id != admin_chat:
                if len(str(chat_id)) == 10 and str(chat_id).startswith('2'):
                    try:
                        send_message(chat_id, message_text)
                        if additional_text.strip():
                            time.sleep(interval_sec)
                            send_message(chat_id, additional_text)
                        time.sleep(interval_sec)
                    except Exception as e:
                        error_msg = str(e)
                        if '[917]' in error_msg:
                            print(f'\n[!] Ошибка доступа к чату {chat_id}. Сообщение НЕ отправлено, но чат сохранён.')
                        else:
                            print(f'\n[!] Произошла ошибка: {e}. Сообщение не отправлено, чат {chat_id} оставлен для повторной отправки.')
                else:
                    print(f'\n[!] Предупреждение: ID {chat_id} не является беседой. Сообщение не отправлено.')


broadcast_thread = threading.Thread(target=broadcast_message)
broadcast_thread.daemon = True
broadcast_thread.start()

# Основной цикл обработки событий
while True:
    if not longpoll_enabled:
        print("[!] Long Poll не активен. Бот ожидает команды вручную...")
        time.sleep(10) # Пауза перед повторной попыткой
        continue

    try:
        for event in longpoll.listen():
            if event.type == VkBotEventType.MESSAGE_NEW:
                message = event.obj.message
                chat_id = message['peer_id']
                text = message['text']

                # Все команды работают только для администраторов
                # Проверяем, является ли отправитель администратором по его user_id
                user_id = message['from_id']
                if user_id not in admin_ids:
                    if text.startswith('.'):
                        send_message(chat_id, "❌ Использование команд бота разрешено только администраторам.")
                    continue

                if text == '.аллид':
                    try:
                        # Получаем список бесед, где состоит бот
                        response = vk.messages.getConversations(filter='all', extended=1, count=200)
                        conversations = response.get('items', [])  # В новых версиях VK API 'items' содержит объекты бесед
                        
                        if not conversations:
                            send_message(chat_id, "Бот не состоит ни в одной беседе.")
                        else:
                            result = "📋 Все чаты, где есть бот:\n\n"
                            for conv in conversations:
                                peer_id = conv.get('peer', {}).get('id')
                                
                                # Формируем ссылку только для бесед
                                if peer_id and str(peer_id).startswith('2000000'):
                                    link = f"https://vk.me/c/{peer_id - 2000000000}"
                                    result += f"🔹 ID: {peer_id} — [Ссылка]({link})\n"
                                
                            send_message(chat_id, result)
                    except Exception as e:
                        send_message(chat_id, f"Ошибка при получении списка чатов: {str(e)}")
                elif text.startswith('.текст'):
                    try:
                        message_text = text.split(' ', 1)[1]
                        save_data()
                        send_message(chat_id, f"Текст для рассылки установлен: {message_text}")
                    except IndexError:
                        send_message(chat_id, "Неверный формат команды. Используйте: .текст [текст]")
                elif text == '.список':
                    total_chats = len(chat_ids)
                    chat_list = "\n".join(str(cid) for cid in chat_ids)
                    send_message(chat_id, f"Количество чатов для рассылки: {total_chats}\nСписок чатов:\n{chat_list}")
                elif text == '.рассылка':
                    reset_event.clear()
                    reset_event.set()
                    send_message(admin_chat, "Рассылка запущена и таймер сброшен.")
                elif text == '.ид':
                    # В VK всегда peer_id = chat_id для бесед
                    send_message(chat_id, f"✅ ID этой беседы: {chat_id}")
                elif text == '.инфо':
                    send_message(chat_id, f"🔸 Настройки:\n\nКД между сообщениями: {cd_min} минут.\nИнтервал рассылки: {interval_sec} секунд.\nТекст рассылки:\n\n{message_text}\nДополнительное сообщение:\n\n{additional_text}")
                elif text == '.хелп':
                    help_text = (
                        "📋 Доступные команды:\n"
                        "\n"
                        "🔹 .текст [текст] — установить текст для рассылки\n"
                        "🔹 .смс [текст] — отправить сообщение один раз во все чаты\n"
                        "🔹 .рассылка — запустить рассылку\n"
                        "🔹 .список — показать количество чатов\n"
                        "🔹 .ид — узнать ID текущего чата\n"
                        "🔹 .аллид — показать все чаты, где есть бот, с ID и ссылками\n"
                        "🔹 .инфо — показать текущие настройки\n"
                        "🔹 .пинг — проверить, работает ли бот\n"
                        "🔹 .хелп — показать это сообщение\n"
                        "🔹 .админ — установить текущий чат как административный\n"
                        "🔹 .уст — добавить текущий чат в список рассылки\n"
                        "🔹 .узид [ссылка на чат] — узнать ID чата по ссылке\n"
                        "🔹 .добид [ID] — добавить чат в список по ID\n"
                        "🔹 .делид [ID] — удалить чат из списка по ID\n"
                        ""
                    )
                    send_message(chat_id, help_text)
                elif text == '.пинг':
                    send_message(chat_id, 'Бот работает в штатном режиме.')
                elif text.startswith('.смс'):
                    try:
                        sms_message = text.split(' ', 1)[1]
                        send_message(chat_id, f"Текст для единоразовой рассылки установлен: {sms_message}")
                        for target_chat_id in chat_ids:
                            if target_chat_id != admin_chat:
                                try:
                                    send_message(target_chat_id, sms_message)
                                    time.sleep(interval_sec)
                                except Exception as e:
                                    print(f'\n[!] Произошла ошибка: {e}\n[ID]: {chat_id}\n[*] Удаляем чат из списка для рассылки')
                                    chat_ids.remove(target_chat_id)
                                    save_data()
                    except IndexError:
                        send_message(chat_id, "Неверный формат команды. Используйте: .смс [текст]")
                elif text.startswith('.узид '):
                    # Извлекаем ссылку из команды
                    link = text[len('.узид '):].strip()
                    if 'vk.me/join/' in link:
                        try:
                            # Извлекаем ключ из ссылки (после /join/ и до =)
                            join_key = link.split('vk.me/join/')[-1].split('=')[0]
                            # В VK API нет прямого метода получения peer_id по ссылке-приглашению
                            # Пользователю нужно вручную перейти по ссылке и использовать .ид в чате
                            send_message(chat_id, f"Ссылка-приглашение: {link}\nИзвлечённый ключ: {join_key}\n⚠️ Чтобы узнать ID чата, перейдите по ссылке и используйте команду .ид в беседе.")
                        except Exception as e:
                            send_message(chat_id, f"Ошибка при обработке ссылки: {str(e)}")
                    elif 'c=' in link:
                        try:
                            chat_id_from_link = link.split('c=')[1].split('&')[0].split(',')[0]
                            if chat_id_from_link.isdigit():
                                send_message(chat_id, f"ID чата из ссылки: {chat_id_from_link}")
                            else:
                                send_message(chat_id, "Не удалось извлечь ID из ссылки.")
                        except Exception:
                            send_message(chat_id, "Ошибка при извлечении ID из ссылки.")
                    else:
                        send_message(chat_id, "Ссылка не является ни ссылкой vk.me/join, ни содержит параметр 'c='." )
                elif text.startswith('.делид '):
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
                # Команда .админ доступна только из любого чата, если админ ещё не установлен
                # После установки только админ может выполнить эту команду
                elif text == '.админ':
                    if admin_chat is None:
                        if chat_id in admin_ids:
                            admin_chat = chat_id
                            save_data()
                            send_message(chat_id, "Этот чат установлен как административный.")
                    elif chat_id in admin_ids:
                        admin_chat = chat_id
                        save_data()
                        send_message(chat_id, "Административный чат изменён.")
                    else:
                        send_message(chat_id, "❌ Установка админ-чата разрешена только администраторам.")
                    if chat_id == admin_chat:
                        send_message(chat_id, "⚠️ Этот чат уже является административным.")
                    elif chat_id in admin_ids:
                        admin_chat = chat_id
                        save_data()
                        send_message(chat_id, "Административный чат изменён.")
                    else:
                        send_message(chat_id, "❌ Установка админ-чата разрешена только администраторам.")
                elif text == '.уст':
                    # Команда .уст доступна только в админ-чате
                    if admin_chat == chat_id:
                        if admin_chat is not None:
                            if len(str(chat_id)) == 10 and str(chat_id).startswith('2'):
                                chat_ids.append(chat_id)
                                save_data()
                                send_message(chat_id, "Этот чат добавлен в список для рассылки сообщений.")
                            else:
                                send_message(chat_id, "Невозможно добавить этот чат: это не беседа.")
                        else:
                            send_message(chat_id, "Администратор не установлен.")
                    else:
                        send_message(chat_id, "❌ Эта команда доступна только из административного чата.")
    except Exception as e:
        print(f'[!] Произошла ошибка: {e}')
        time.sleep(5)