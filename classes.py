import json, time
from typing import Literal

EMOJIS = Literal[
    '❤️','👍','🤣','🔥','💯','😍','🎉','⚡',
    '🤩','🤘','😎','🙄','😐','😁','🤪','😉',
    '🤤','😇','😘','🥰','🥳','🌚','🌝','😴',
    '🫠','🤔','🫡','😳','🥱','🐈','🐶','💪',
    '🤞','👋','👏','🤝','👌','🙏','💋','👑',
    '⭐','🍷','🍑','🤷‍♀️','🤷‍♂️','👩‍❤️‍👨','🦄','👻',
    '🗿','👀','👁️','🖤','❤️‍🩹','🛑','⛄','❓',
    '❗️'
]

# region Name
class Name:
    def __init__(self, **kwargs):
        """
        Represents a name structure for a contact.

        This class stores name-related information for a contact, including a full name,
        first name, last name, and type.
        """
        self.name = kwargs.get('name')
        self.first_name = kwargs.get('firstName')
        self.last_name = kwargs.get('lastName')
        self.type = kwargs.get('type')

# region Contact
class Contact:
    def __init__(self, client, accountStatus = None, baseUrl = None, names = None, phone = None, description = None, options = None, photoId = None, updateTime = None, id = None, baseRawUrl = None, gender = None, link = None, **kwargs):
        """
        Represents a contact with detailed profile information.

        This class encapsulates contact details, including status, URLs, names (as `Name` objects),
        phone number, description, and other metadata.
        """
        self._client = client
        self.accountStatus = accountStatus
        self.base_url = baseUrl
        self.names = [Name(**n) for n in names] if names else []
        self.phone = phone
        self.description = description
        self.options = options
        self.photo_id = photoId
        self.update_time = updateTime
        self.id = id
        self.link = link
        self.gender = gender
        self.base_raw_url = baseRawUrl
    
    # region add()
    def add(self):
        return self._client.contact_add(self.id)
    
    # region remove()
    def remove(self):
        return self._client.contact_remove(self.id)
    
    # region block()
    def block(self):
        return self._client.contact_block(self.id)
    
    # region unblock()
    def unblock(self):
        return self._client.contact_unblock(self.id)

# region User
class User:
    def __init__(self, client, profile, _f=0):
        """
        Represents a user with a contact profile.

        This class wraps a `Contact` object created from a profile dictionary, typically
        received from the server.
        """
        self._client = client
        self.contact = Contact(client, **profile)
        _id = client.me.contact.id if client.me else profile["id"]
        if not _f:
            self.chat = Chat(self._client, profile["id"] ^ _id)

        if profile["id"] != _id:

            pass

# region Chat
class Chat:
    def __init__(self, client, chat_id):
        """
        Represents a chat in the messaging system.

        This class associates a chat with a client instance and its unique ID.
        """
        if chat_id == 0:
            return
        self._client = client

        self.id: int = chat_id
        self.link = f"https://web.max.ru/{chat_id}"

        seq = client.seq
        client.websocket.send(json.dumps({"ver":11,"cmd":0,"seq":seq,"opcode":49,"payload":{"chatId":chat_id,"from":int(time.time()*1000),"forward":0,"backward":30,"getMessages":True}}))
        while True:
            r = client.websocket.recv()
            recv = json.loads(r)
            if recv["seq"] == seq and recv["opcode"] == 49:
                break
            else:
                pass
        
        payload = recv["payload"]
        if not recv["opcode"] in [150]:
            _ = []
            for msg in payload["messages"]:
                m = Message(client, 0, **msg, _f=1)
                _.append(m)
            self.messages: list[Message] = _

    # region pin()
    def pin(self):
        self._client.pin_chat(self.id)

    # region unpin()
    def unpin(self):
        self._client.unpin_chat(self.id)

    def clear_history(self): # TODO
        # seq = self.seq
        # {"ver":11,"cmd":0,"seq":seq,"opcode":48,"payload":{"chatIds":[chatid]}}
        pass

# region Message
class Message:
    def __init__(self, client, chatId: str, sender: str, id, time, text, type, _f=0, **kwargs):
        """
        Represents a message in a chat.

        This class encapsulates message details, including the sender, content, and metadata,
        and provides methods to interact with the message (e.g., reply, delete, edit).
        """
        self._client = client
        self.kwargs = kwargs
        self.status = kwargs.get("status")

        if not _f:
            self.chat = Chat(client, chatId)
        self.sender = sender
        self.id = id
        self.time = time
        self.text = text
        self.type = type
        self.update_time = kwargs.get("updateTime")
        self.options = kwargs.get("options")
        self.cid = kwargs.get("cid")
        self.attaches = kwargs.get("attaches", [])
        self.reaction_info = kwargs.get("reactionInfo", {})
        self.user: User = client.get_user(id=sender, _f=1)
    
    # region reply()
    def reply(self, text: str, **kwargs) -> "Message":
        """
        Replies to the current message in its chat.

        This method sends a new message in the same chat, linking it as a reply to the current message.

        Args:
            text (str): The text content of the reply.
            **kwargs: Additional arguments to pass to `send_message` (e.g., notify).

        Returns:
            Message: A `Message` object representing the sent reply.

        Usage:
            ```python
            reply_msg = message.reply("Thanks for your message!")
            ```
        """
        return self._client.send_message(self.chat.id, text, self.id, **kwargs)
    
    # region answer()
    def answer(self, text: str, **kwargs) -> "Message":
        """
        Sends a new message in the same chat without linking it as a reply.

        This method sends a message to the same chat as the current message, without referencing it.

        Args:
            text (str): The text content of the message.
            **kwargs: Additional arguments to pass to `send_message` (e.g., notify).

        Returns:
            Message: A `Message` object representing the sent message.

        Usage:
            ```python
            new_msg = message.answer("Got it, sending a follow-up.")
            ```
        """
        return self._client.send_message(self.chat.id, text, **kwargs)

    # region delete()
    def delete(self, for_me = False):
        """
        Deletes the current message from its chat.

        This method deletes the message, either for the current user only or for all chat participants.

        Args:
            for_me (bool, optional): If True, deletes the message only for the current user. Defaults to False.

        Usage:
            ```python
            # Delete message for all
            message.delete()
            
            # Delete message only for the current user
            message.delete(for_me=True)
            ```
        """
        return self._client.delete_message(self.chat.id, [self.id], for_me)
    
    # region edit()
    def edit(self, text: str) -> "Message":
        """
        Edits the text content of the current message.

        This method updates the message's text and returns the updated `Message` object.

        Args:
            text (str): The new text content for the message.

        Returns:
            Message: A `Message` object representing the edited message.

        Usage:
            ```python
            updated_msg = message.edit("Updated message text!")
            print(updated_msg.text)  # Output: Updated message text!
            ```
        """
        return self._client.edit_message(self.chat.id, self.id, text)
    
    # region react()
    def react(self, reaction: EMOJIS) -> "Reactions":
        """
        Reacts to the current message with a specified emoji.

        Args:
            reaction (EMOJIS): The emoji reaction to be added, represented by an EMOJIS enum.

        Returns:
            Reactions: An object containing updated reaction information for the message.
        """
        return self._client.set_reaction(self.chat.id, self.id, reaction)

# region Reaction
class Reaction:
    def __init__(self, reaction: str, count: int):
        self.reaction = reaction
        self.count = count

# region Reactions
class Reactions:
    def __init__(self, **kwargs):
        reaction_info = kwargs.get('reactionInfo', {})
        self.counters = [Reaction(**c) for c in reaction_info.get('counters', [])]
        self.your_reaction = reaction_info.get('yourReaction')
        self.total_count = reaction_info.get('totalCount')
