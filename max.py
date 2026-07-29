from websockets.sync.client import connect
from websockets.exceptions import ConnectionClosedError
import json
import queue
import threading
import time
from uuid import uuid4
from classes import *
from errors import *

# region class MaxClient
class MaxClient:
    def __init__(self, token: str|None = None, phone: str|None = None):
        """
        Initializes a new instance of the MaxClient class.

        This constructor sets up the client with optional authentication token and phone number.
        It prepares internal state for sequence numbering, user agent generation, WebSocket connection,
        and event handlers.

        Usage:
            ```
            # You can use only token or only phone if have one.
            client = MaxClient(token="token", phone="number")
            # Now you can use client methods like connect(), auth(), etc.
            ```
        """

        # print("Loaded WebMaxLib")

        self._seq = 0

        self.phone_number = phone
        self.auth_token = token
        self.user_agent = self._generate_user_agent()

        self.websocket = None
    
        self._19_payload = None
        self._on_connect = None
        self._connected = False
        self._t = None
        self._t_stop = False

        self.is_log_in = False
        self.me = None
        self.session_id = int(time.time()*1000)

        self.handlers = []
        self._pending: dict[int, queue.Queue] = {}
        self._pending_lock = threading.Lock()
        self._send_lock = threading.Lock()
        self._event_queue: queue.Queue = queue.Queue()
        self._user_cache: dict = {}
        self._worker_thread = None
        self.connected_at_ms = 0

    # region seq
    @property
    def seq(self):
        current_seq = self._seq
        self._seq += 1
        return current_seq

    def invoke_method(self, opcode: int, payload: dict, timeout: float = 30):
        """Send RPC and wait for matching seq response (listener delivers it)."""
        if not self.websocket:
            raise RuntimeError("WebSocket not connected")
        seq = self.seq
        waiter: queue.Queue = queue.Queue(maxsize=1)
        with self._pending_lock:
            self._pending[seq] = waiter
        packet = {
            "ver": 11,
            "cmd": 0,
            "seq": seq,
            "opcode": opcode,
            "payload": payload,
        }
        with self._send_lock:
            self.websocket.send(json.dumps(packet))
        try:
            return waiter.get(timeout=timeout)
        except queue.Empty:
            with self._pending_lock:
                self._pending.pop(seq, None)
            raise TimeoutError(f"No response for opcode={opcode} seq={seq}")
    
    # region cid
    @property
    def cid(self):
        return int(time.time() * 1000)
    
    # region marker
    @property
    def marker(self):
        return int("900"+str(int(time.time())))

    # region _generate_user_agent()
    def _generate_user_agent(self) -> str:
        return json.dumps({
            "ver": 11,
            "cmd": 0,
            "seq": self.seq,
            "opcode": 6,
            "payload": {
                "userAgent": {
                    "deviceType": "WEB",
                    "locale": "en",
                    "osVersion": "Windows",
                    "deviceName": "WebMax Lib",
                    "headerUserAgent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36",
                    "deviceLocale": "en",
                    "appVersion": "4.8.42",
                    "screen": "1920x1080 1.0x",
                    "timezone": "UTC"
                },
                "deviceId": str(uuid4())
            }
        })

    # region connect()
    def connect(self, _f=None):
        """
        Establishes a WebSocket connection to the server.

        This method connects to the WebSocket endpoint, sends the user agent, and authenticates using the token.
        It sets the client to connected state and retrieves the user profile.

        Usage:
            ```
            # You can use only token or only phone if have one.
            client = MaxClient(token="token", phone="number")
            client.connect()
            # Call this after setting the auth_token to establish the connection.
            ```
        """
        if self._connected:
            return
        headers = [
            ("Origin", "https://web.oneme.ru"),
            ("Pragma", "no-cache"),
            ("Cache-Control", "no-cache"),
            ("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36")
        ]
        self.websocket = connect("wss://ws-api.oneme.ru/websocket", additional_headers=headers)
        self.websocket.send(self.user_agent)
        self.websocket.recv()

        if _f:
            return

        self.websocket.send(json.dumps({
            "ver": 11,
            "cmd": 0,
            "seq": self.seq,
            "opcode": 19, 
            "payload": {
                "interactive": True,
                "token": self.auth_token,
                "chatsSync": 0,
                "contactsSync": 0,
                "presenceSync": 0,
                "draftsSync": 0,
                "chatsCount": 40
            }
        }))

        p = json.loads(self.websocket.recv())['payload']
        usr = User(self, p['profile'])
        self.me = usr
        self._connected = True
        self.connected_at_ms = int(time.time() * 1000)

        if self._on_connect:
            self._on_connect()

    # region disconnect()
    def disconnect(self):
        """
        Closes the WebSocket connection and resets the client state.

        This method safely disconnects from the server and resets internal flags and sequence.

        Usage:
            ```
            # You can use only token or only phone if have one.
            client = MaxClient(token="token", phone="number")
            client.disconnect()
            # Call this to cleanly close the connection when done.
            ```
        """
        if not self._connected:
            return
        if self.websocket:
            self.websocket.close()
            self._seq = 0
        self._connected = False
        self.websocket = None

    # region set_token()
    def set_token(self, token):
        """
        Sets the authentication token for the client.

        This updates the auth_token used for connecting to the server.

        Usage:
            ```
            # You can use only token or only phone if have one.
            client = MaxClient(token="token", phone="number")
            client.set_token("new_auth_token")
            # Use this to update the token before connecting or reconnecting.
            ```
        """
        self.auth_token = token

    # region _hlprocessor()
    def _hlprocessor(self, msg: Message):
        """Internal worker. Don't touch."""
        for filter, func in self.handlers:
            if filter(self, msg):
                func(self, msg)
                return  

    def _heartbeat(self):
        """Отправляет пинг серверу каждые 25 секунд"""
        while self._connected and not self._t_stop:
            try:
                with self._send_lock:
                    if self.websocket:
                        self.websocket.send(json.dumps({
                            "ver": 11,
                            "cmd": 0,
                            "seq": self.seq,
                            "opcode": 1,
                            "payload": {"interactive": False}
                        }))
            except Exception as e:
                print("Heartbeat error:", e)
            time.sleep(25)


    # region _listener()
    def _listener(self):
        """Only reads websocket: routes RPC replies and queues incoming messages."""
        while not self._t_stop:
            try:
                recv = json.loads(self.websocket.recv())
            except ConnectionClosedError:
                self._connected = False
                try:
                    if self.websocket:
                        self.websocket.close()
                except Exception:
                    pass
                time.sleep(3)
                try:
                    self.connect()
                    self._connected = True
                    print(f"Переподключено, сессия с {self.connected_at_ms}")
                except Exception as ee:
                    print("Не смог встать:", ee)
                    time.sleep(5)
                continue

            except Exception as e:
                print("Иная беда:", e)
                self._connected = False
                time.sleep(5)
                continue

            seq = recv.get("seq")
            with self._pending_lock:
                waiter = self._pending.pop(seq, None) if seq is not None else None
            if waiter is not None:
                waiter.put(recv)
                continue

            opcode = recv.get("opcode")
            if opcode == 128:
                self._event_queue.put(recv)
            # opcode 1 keepalive replies — ignore

    def _worker(self):
        """Processes incoming messages off the listener thread."""
        while not self._t_stop:
            try:
                recv = self._event_queue.get(timeout=1)
            except queue.Empty:
                continue
            try:
                payload = recv.get("payload") or {}
                msg = Message(self, payload["chatId"], **payload["message"])
                self._hlprocessor(msg)
            except Exception as e:
                print("Ошибка обработки сообщения:", e)


    # region run()
    def run(self):
        """
        Starts the client by connecting and launching the listener thread.

        This connects to the server and begins listening for messages in a background thread.

        Usage:
            ```
            # You can use only token or only phone if have one.
            client = MaxClient(token="token", phone="number")
            client.run()
            ```
        """
        self.connect()
        self._t_stop = False
        self._t = threading.Thread(target=self._listener, name="WebMaxListener", daemon=True)
        self._t.start()
        self._worker_thread = threading.Thread(target=self._worker, name="WebMaxWorker", daemon=True)
        self._worker_thread.start()
        threading.Thread(target=self._heartbeat, name="WebMaxHeartbeat", daemon=True).start()
        # Keep process alive
        try:
            while not self._t_stop:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()
    
    def stop(self):
        """
        Stops the listener thread and disconnects from the server.

        This signals the listener to stop and closes the connection.

        Usage:
            ```
            # You can use only token or only phone if have one.
            client = MaxClient(token="token", phone="number")

            @client.on_connect # Using onconnect decorator
            def onconnect():
                client.stop() # Stops client after run

            client.run()
            ```
        """
        self._t_stop = True
        self.disconnect()

    # region _start_auth()
    def _start_auth(self, phone_number) -> dict:
        """
        Initiates the authentication process by sending a phone number to receive a verification code.

        This sends a request to start authentication and returns the server response.

        Usage:
            ```
            # You can use only token or only phone if have one.
            client = MaxClient(token="token", phone="number")
            response = client._start_auth("your_phone_number")
            ```
        """
        self.connect(_f=1)
        if self.is_log_in:
            raise ValueError("Client is logged in now")
        
        self.websocket.send(json.dumps({
            "ver": 11,
            "cmd": 0,
            "seq": self.seq,
            "opcode": 17,
            "payload": {
                "phone": phone_number,
                "type": "START_AUTH",
                "language": "ru"
            }
        }))

        return json.loads(self.websocket.recv()) # experimental
    
    # region _check_code()
    def _check_code(self, token, code) -> dict:
        self.websocket.send(json.dumps({
            "ver": 11,
            "cmd": 0,
            "seq": self.seq,
            "opcode": 18,
            "payload": {
                "token": token,
                "verifyCode": code,
                "authTokenType": "CHECK_CODE"
            }
        }))

        token_resp = json.loads(self.websocket.recv())
        payload = token_resp['payload']
        error = token_resp['payload'].get("error", None)

        if error == "verify.code.wrong":
            raise VerifyCodeWrong(payload["error"], payload["title"])
        return token_resp

    # region auth()
    def auth(self, phone_number: str):
        """
        Performs the full authentication process interactively.

        This connects, starts auth, prompts for the code, verifies it, and sets the auth_token.
        Returns the User object for the authenticated user.

        Usage:
        ```
        user = client.auth("+7xxxxxxxxxx")
        # Follow the prompt to enter the SMS code.
        ```
        """

        code_resp = self._start_auth(phone_number)

        if code_resp.get('payload', {}).get('error'):
            raise ValueError(code_resp['payload']['error'] + ": " + code_resp['payload']['localizedMessage'])
            
        token = code_resp['payload']['token']
        print(f"Auth token received. Please enter the code sent to your phone.\n")

        while True:
            try:
                code = input("Auth code: ")
                token_resp = self._check_code(token, code)

                payload = token_resp['payload']
                break

            except VerifyCodeWrong as vcw:
                print(f"{vcw.title} ({vcw.error})")
                continue

            except Exception as e:
                print(e)
                continue

        self.auth_token = payload['tokenAttrs']['LOGIN']['token']
        usr = User(self, payload['profile'])
        self.me = usr
        return self.me

    # region get_chats()
    # DONT USE THIS! BROKEN
    # def get_chats(self, count = 40) -> dict:
    #     if not self.auth_token:
    #         raise ValueError("No auth token provided. Please authenticate first.")

    #     self.websocket.send(json.dumps({
    #         "ver": 11,
    #         "cmd": 0,
    #         "seq": self.seq,
    #         "opcode": 19,
    #         "payload": {
    #             "interactive": True,
    #             "token": self.auth_token,
    #             "chatsSync": 0,
    #             "contactsSync": 0,
    #             "presenceSync": 0,
    #             "draftsSync": 0,
    #             "chatsCount": count
    #         }
    #     }))

    #     response = json.loads(self.websocket.recv())
    #     return response

    # region send_message()
    def send_message(self, chat_id: int, text: str, reply_id: str|int = None, notify: bool = True):
        """
        Sends a text message to a specified chat.

        This method constructs and sends a text message to the given chat ID, with an optional reply to another message.
        It waits for the server response with the matching sequence number and returns a `Message` object.

        Args:
            chat_id (int): The ID of the chat to send the message to.
            text (str): The text content of the message.
            reply_id (str | int, optional): The ID of the message to reply to. Defaults to None.
            notify (bool, optional): Whether to notify chat participants. Defaults to True.

        Returns:
            Message: A `Message` object representing the sent message.

        Raises:
            ValueError: If the client is not connected or authenticated.
            Exception: If the server response cannot be parsed into a `Message` object.

        Usage:
            ```python
            # Send a simple message
            msg = client.send_message(12345678, "Hello, world!")
            
            # Send a message with a reply
            msg = client.send_message(12345678, "Replying to you!", reply_id=987654)
            ```
        """
        payload = {
            "chatId": chat_id,
            "message": {
                "text": text,
                "cid": self.cid,
                "elements": [],
                "attaches": []
            },
            "notify": notify
        }

        if reply_id:
            payload["message"]["link"] = {
                "type": "REPLY",
                "messageId": str(reply_id)
            }

        recv = self.invoke_method(64, payload)
        payload = recv["payload"]
        try:
            msg = Message(self, payload["chatId"], **payload["message"])
            return msg
        except Exception:
            raise

    # region delete_message()
    def delete_message(self, chat_id: int, message_ids: list[str], for_me: bool = False):
        """
        Deletes one or more messages from a specified chat.

        This method sends a request to delete messages identified by their IDs in the given chat.
        The `for_me` parameter determines whether the deletion is only for the current user or for all chat participants.

        Args:
            chat_id (int): The ID of the chat containing the messages.
            message_ids (list[str]): A list of message IDs to delete.
            for_me (bool, optional): If True, deletes the messages only for the current user. Defaults to False.

        Raises:
            ValueError: If the client is not connected or authenticated.

        Usage:
            ```python
            # Delete messages for all participants
            client.delete_message(12345678, ["1000121", "1000122"])
            
            # Delete messages only for the current user
            client.delete_message(12345678, ["1000120"], for_me=True)
            ```
        """
        self.invoke_method(66, {
            "chatId": chat_id,
            "messageIds": message_ids,
            "forMe": for_me
        })

    # region edit_message()
    def edit_message(self, chat_id: int, message_id: str|int, text: str):
        """
        Edits the text of an existing message in a specified chat.

        This method sends a request to update the text of a message identified by its ID in the given chat.
        It waits for the server response with the matching sequence number and returns the updated `Message` object.

        Args:
            chat_id (int): The ID of the chat containing the message.
            message_id (str | int): The ID of the message to edit.
            text (str): The new text content for the message.

        Returns:
            Message: A `Message` object representing the edited message.

        Raises:
            ValueError: If the client is not connected, not authenticated, or the response cannot be parsed.

        Usage:
            ```python
            # Edit an existing message
            updated_msg = client.edit_message(12345678, "12111121", "New text")
            ```
        """
        recv = self.invoke_method(67, {
            "chatId": chat_id,
            "messageId": str(message_id),
            "text": text,
            "elements": [],
            "attachments": []
        })
        payload = recv["payload"]
        msg = Message(self, chat_id, **payload["message"])
        return msg
    
    # region pin_chat()
    def pin_chat(self, chat_id: int|str):
        j = {
            "ver": 11,
            "cmd": 0,
            "seq": self.seq,
            "opcode": 22,
            "payload": {
                "settings": {
                    "chats": {
                        str(chat_id): {
                            "favIndex": int(time.time()*1000)
                        }
                    }
                }
            }
        }
        with self._send_lock:
            self.websocket.send(json.dumps(j))
        return True

    # region unpin_chat()
    def unpin_chat(self, chat_id: int|str):
        j = {
            "ver": 11,
            "cmd": 0,
            "seq": self.seq,
            "opcode": 22,
            "payload": {
                "settings": {
                    "chats": {
                        str(chat_id): {
                            "favIndex": 0
                        }
                    }
                }
            }
        }
        with self._send_lock:
            self.websocket.send(json.dumps(j))
        return True
    
    # region get_user()
    def get_user(self, **kwargs):
        """
        Retrieves a user's profile by their ID or phone number.

        Args:
            - id (int, optional) : The contact ID of the user to retrieve.
            - phone (str, optional) : The phone number of the user to retrieve.
            - chat_id (int, optional) : The chat ID with the user to retrieve.

        Returns:
            User: A `User` object representing the retrieved user's profile.

        Raises:
            ValueError: If neither `id` nor `phone` is provided, or if the client is not connected or authenticated.
            WebSocketError: If there is an issue with the WebSocket communication.

        Usage:
            ```python
            # Get user by ID
            user = client.get_user(id="123456")
            print(user.contact.names[0].name)  # Prints the user's full name

            # Get user by phone number
            user = client.get_user(phone="+7xxxxxxxxxx")
            print(user.contact.phone)  # Prints the user's phone number
        """
        id = kwargs.get('id')
        phone = kwargs.get('phone')
        chat_id = kwargs.get('chat_id')
        _f = kwargs.get("_f")

        cache_key = id if id is not None else (f"phone:{phone}" if phone else None)
        if cache_key is not None and cache_key in self._user_cache:
            return self._user_cache[cache_key]

        if id:
            opcode, req_payload = 32, {"contactIds": [id]}
        elif phone:
            opcode, req_payload = 46, {"phone": str(phone)}
        elif chat_id:
            id = self.me.contact.id ^ chat_id
            opcode, req_payload = 32, {"contactIds": [id]}
        else:
            raise ValueError("no `id` or `phone` or `chat_id` provided")

        recv = self.invoke_method(opcode, req_payload)
        payload = recv["payload"]

        error = payload.get("error")

        if error:
            raise UserNotFound(error, payload.get("message", "") + f": {phone}")

        if id:
            contact = payload["contacts"][0]
        if phone:
            payload["contact"]["phone"] = phone
            contact = payload["contact"]

        user = User(self, contact, _f)
        if cache_key is not None:
            self._user_cache[cache_key] = user
        return user

    # region session_exit()
    def session_exit(self):
        """Terminates active session token. **There no way back.**"""
        j = {"ver":11,"cmd":0,"seq":self.seq,"opcode":20,"payload":{}}
        with self._send_lock:
            self.websocket.send(json.dumps(j))
        self.disconnect()
        return True
    
    # region set_reaction()
    def set_reaction(self, chat_id, message_id, reaction: EMOJIS):
        """
        Sets a reaction to a specific message in a chat.

        This function sends a reaction to a message and return a Reactions object.

        Args:
            chat_id (str): The unique identifier of the chat.
            message_id (str): The unique identifier of the message.
            reaction (EMOJIS): The emoji reaction to be set, using the EMOJIS enumeration.

        Returns:
            Reactions: An object containing information about the updated message reactions,
                    including counters for each emoji, your own reaction, and the total count.
        """
        recv = self.invoke_method(
            178,
            {
                "chatId": chat_id,
                "messageId": message_id,
                "reaction": {"reactionType": "EMOJI", "id": reaction},
            },
        )
        return Reactions(**recv["payload"])
    
    # region contact_add()
    def contact_add(self, user_id: int):
        recv = self.invoke_method(34, {"contactId": user_id, "action": "ADD"})
        return User(self, recv["payload"]["contact"])
    
    # region contact_remove()
    def contact_remove(self, user_id: int):
        self.invoke_method(34, {"contactId": user_id, "action": "REMOVE"})
        return True
    
    # region contact_block()
    def contact_block(self, user_id: int):
        self.invoke_method(34, {"contactId": user_id, "action": "BLOCK"})
        return True
    
    # region contact_unblock()
    def contact_unblock(self, user_id: int):
        self.invoke_method(34, {"contactId": user_id, "action": "UNBLOCK"})
        return True
                
    # region @on_message()
    def on_message(self, filters):
        """
        Decorator to register a handler for a specific message type.

        This allows defining functions to handle certain events or messages by text key.

        Usage:
        ```
        from max import MaxClient as Client
        from filters import filters
        from classes import Message

        client = Client("token")

        @client.on_message(filters.command("hello"))
        def command_hello(client: Client, message: Message):
            message.reply("Max - самый забагованный мессенджер.")
        # The decorated function will be called when the filter event occurs.

        client.run()
        ```
        """
        def decorator(func):
            self.handlers.append((filters, func))
            return func

        return decorator
    
    # region get_file_download_url
    def get_file_download_url(self, file_id, chat_id=None, message_id=None):
        """Resolve a direct download URL for a FILE attach (opcode 88)."""
        try:
            payload = {"fileId": file_id}
            if chat_id is not None:
                payload["chatId"] = chat_id
            if message_id is not None:
                payload["messageId"] = str(message_id)
            recv = self.invoke_method(88, payload)
            p = recv.get("payload") or {}
            if p.get("error"):
                print("file download error:", p)
                return None
            return p.get("url")
        except Exception as e:
            print("get_file_download_url:", e)
            return None

    def get_video_download_urls(
        self,
        video_id,
        chat_id=None,
        message_id=None,
        token=None,
    ) -> list[str]:
        """Resolve MP4 CDN URLs for a VIDEO attach (opcode 83)."""
        try:
            payload = {"videoId": video_id}
            if chat_id is not None:
                payload["chatId"] = chat_id
            if message_id is not None:
                payload["messageId"] = str(message_id)
            if token:
                payload["token"] = token
            recv = self.invoke_method(83, payload)
            p = recv.get("payload") or {}
            if p.get("error"):
                print("video download error:", p)
                return []

            # Prefer higher quality progressive MP4 over HLS/EXTERNAL
            preferred = (
                "MP4_1080", "MP4_720", "MP4_480", "MP4_360", "MP4_240",
                "DASH", "HLS",
            )
            urls: list[str] = []
            for key in preferred:
                val = p.get(key)
                if isinstance(val, str) and val.startswith("http"):
                    urls.append(val)
            for key, val in p.items():
                if key in ("cache", "EXTERNAL") or not isinstance(val, str):
                    continue
                if val.startswith("http") and val not in urls:
                    urls.append(val)
            if isinstance(p.get("url"), str):
                urls.append(p["url"])
            # drop m3u8 / dash manifests — need progressive file for TG
            urls = [u for u in urls if ".m3u8" not in u.lower() and "manifest" not in u.lower()]
            print(f"video urls for {video_id}: {len(urls)} candidates keys={list(p.keys())}")
            return urls
        except Exception as e:
            print("get_video_download_urls:", e)
            return []

    def get_video_download_url(self, video_id, chat_id=None, message_id=None, token=None):
        urls = self.get_video_download_urls(video_id, chat_id, message_id, token)
        return urls[0] if urls else None

    #region @on_connect
    def on_connect(self, func):
        """
        Registers a callback function to be called upon successful connection.

        This sets a handler that is invoked after connecting and authenticating.

        Usage:
        ```
        from max import MaxClient as Client

        client = Client("token")

        @client.on_connect
        def on_connect_handler():
            print("Connected!")
        # The function will be called automatically on connect.
        client.run()
        ```
        """
        self._on_connect = func
        return func
