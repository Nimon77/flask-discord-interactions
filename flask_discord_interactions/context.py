from dataclasses import dataclass
from typing import Any, List, Union
import inspect
import itertools
import warnings
import types

import requests

from flask_discord_interactions.models import (
    LoadableDataclass, Member, Channel, Role, User, CommandOptionType, ApplicationCommandType, Message
)


@dataclass
class Context(LoadableDataclass):
    """
    Represents the context in which a :class:`Command` or custom ID
    handler is invoked.

    Attributes
    ----------
    author
        A :class:`Member` object representing the invoking user.
    id
        The unique ID (snowflake) of this interaction.
    type
        The :class:`ApplicationCommandType` of this interaction.
    token
        The token to use when sending followup messages.
    channel_id
        The unique ID (snowflake) of the channel this command was invoked in.
    guild_id
        The unique ID (snowflake) of the guild this command was invoked in.
    options
        A list of the options passed to the command.
    values
        A list of the values selected, if this is a Select Menu handler.
    resolved
        Additional data ()
    command_name
        The name of the command that was invoked.
    command_id
        The unique ID (snowflake) of the command that was invoked.
    members
        :class:`Member` objects for each user specified as an option.
    channels
        :class:`Channel` objects for each channel specified as an option.
    roles
        :class:`Role` object for each role specified as an option.
    target
        The targeted :class:`User` or message.
    """
    author: Member = None
    id: str = None
    type: int = None
    token: str = None
    channel_id: str = None
    guild_id: str = None
    options: list = None
    values: list = None
    resolved: dict = None
    command_name: str = None
    command_id: str = None
    members: List[Member] = None
    channels: List[Channel] = None
    roles: List[Role] = None

    app: Any = None
    discord: Any = None

    custom_id: str = None
    primary_id: str = None
    handler_state: list = None

    target_id: str = None
    target: Union[User, Message] = None

    @classmethod
    def from_data(cls, discord=None, app=None, data={}):
        if data is None:
            data = {}

        # If this is a proxy (e.g. flask.current_app), get the current object
        # https://flask.palletsprojects.com/en/2.0.x/reqcontext/#notes-on-proxies
        if hasattr(app, "_get_current_object"):
            app = app._get_current_object()

        result = cls(
            app = app,
            discord = discord,
            author = Member.from_dict(data.get("member", {})),
            id = data.get("id"),
            type = data.get("data", {}).get("type") or ApplicationCommandType.CHAT_INPUT,
            token = data.get("token"),
            channel_id = data.get("channel_id"),
            guild_id = data.get("guild_id"),
            options = data.get("data", {}).get("options"),
            values = data.get("data", {}).get("values", []),
            resolved = data.get("data", {}).get("resolved", {}),
            command_name = data.get("data", {}).get("name"),
            command_id = data.get("data", {}).get("id"),
            custom_id = data.get("data", {}).get("custom_id") or "",
            target_id = data.get("data", {}).get("target_id"),
        )

        result.data = data

        result.parse_custom_id()
        result.parse_resolved()
        result.parse_target()
        return result

    @property
    def auth_headers(self):
        if self.discord:
            return self.discord.auth_headers(self.app)
        else:
            return self.frozen_auth_headers

    def parse_custom_id(self):
        """
        Parse the custom ID of the incoming interaction data.

        This includes the primary ID as well as any state stored in the
        handler.
        """

        self.primary_id = self.custom_id.split("\n", 1)[0]
        self.handler_state = self.custom_id.split("\n")

    def parse_resolved(self):
        """
        Parse the ``"resolved"`` section of the incoming interaction data.

        This section includes objects representing each user, member, channel,
        and role passed as an argument to the command.
        """

        self.members = {}
        for id in self.resolved.get("members", {}):
            member_info = self.resolved["members"][id]
            member_info["user"] = self.resolved["users"][id]
            self.members[id] = Member.from_dict(member_info)

        self.channels = {id: Channel.from_dict(data)
                         for id, data
                         in self.resolved.get("channels", {}).items()}

        self.roles = {id: Role.from_dict(data)
                      for id, data in self.resolved.get("roles", {}).items()}

        self.messages = {
            id: Message.from_dict(data)
            for id, data in self.resolved.get("messages", {}).items()
        }

    def parse_target(self):
        """
        Parse the target of the incoming interaction.

        For User and Message commands, the target is the relevant user or
        message. This method sets the `ctx.target` field.
        """
        if self.type == ApplicationCommandType.USER:
            self.target = self.members[self.target_id]
        elif self.type == ApplicationCommandType.MESSAGE:
            self.target = self.messages[self.target_id]
        else:
            self.target = None

    def create_args(self):
        """
        Create the arguments which will be passed to the function when the
        :class:`Command` is invoked.
        """
        if self.type == ApplicationCommandType.CHAT_INPUT:
            return self.create_args_chat_input()
        elif self.type == ApplicationCommandType.USER:
            return [self.target], {}
        elif self.type == ApplicationCommandType.MESSAGE:
            return [self.target], {}

    def create_args_chat_input(self):
        """
        Create the arguments for this command, assuming it is a ``CHAT_INPUT``
        command.
        """
        def create_args_recursive(data, resolved):
            if not data.get("options"):
                return [], {}

            args = []
            kwargs = {}

            for option in data["options"]:
                if option["type"] in [
                        CommandOptionType.SUB_COMMAND,
                        CommandOptionType.SUB_COMMAND_GROUP]:

                    args.append(option["name"])

                    sub_args, sub_kwargs = create_args_recursive(
                        option, resolved)

                    args += sub_args
                    kwargs.update(sub_kwargs)

                elif option["type"] == CommandOptionType.USER:
                    member_data = resolved["members"][option["value"]]
                    member_data["user"] = resolved["users"][option["value"]]

                    kwargs[option["name"]] = Member.from_dict(member_data)

                elif option["type"] == CommandOptionType.CHANNEL:
                    kwargs[option["name"]] = Channel.from_dict(
                        resolved["channels"][option["value"]])

                elif option["type"] == CommandOptionType.ROLE:
                    kwargs[option["name"]] = Role.from_dict(
                        resolved["roles"][option["value"]])

                else:
                    kwargs[option["name"]] = option["value"]

            return args, kwargs

        return create_args_recursive({"options": self.options}, self.resolved)

    def create_handler_args(self, handler):
        """
        Create the arguments which will be passed to the function when a
        custom ID handler is invoked.

        Parameters
        ----------
        data
            An object with the incoming data for the invocation.
        """

        args = self.handler_state[1:]

        sig = inspect.signature(handler)

        iterator = zip(
            itertools.count(),
            args,
            itertools.islice(sig.parameters.values(), 1, None)
        )

        for i, argument, parameter in iterator:
            annotation = parameter.annotation

            if annotation == int:
                args[i] = int(argument)

            elif annotation == bool:
                if argument == "True":
                    args[i] = True
                elif argument == "False":
                    args[i] = False
                elif argument == "None":
                    args[i] = None
                else:
                    raise ValueError(
                        f"Invalid bool in handler state parsing: {args[i]}")

        return args

    def followup_url(self, message=None):
        """
        Return the followup URL for this interaction. This URL can be used to
        send a new message, or to edit or delete an existing message.

        Parameters
        ----------
        message
            The message to edit or delete. If None, sends a new message. If
            "@original", refers to the original message.
        """

        url = (f"{self.app.config['DISCORD_BASE_URL']}/webhooks/"
               f"{self.app.config['DISCORD_CLIENT_ID']}/{self.token}")
        if message is not None:
            url += f"/messages/{message}"

        return url

    def edit(self, response, message="@original"):
        """
        Edit an existing message.

        Parameters
        ----------
        response
            The new response to edit the message to.
        message
            The message to edit. If omitted, edits the original message.
        """

        response = Message.from_return_value(response)

        if not self.app or self.app.config["DONT_REGISTER_WITH_DISCORD"]:
            return

        response = requests.patch(
            self.followup_url(message),
            json=response.dump_followup(),
            headers=self.auth_headers
        )
        response.raise_for_status()

    def delete(self, message="@original"):
        """
        Delete an existing message.

        Parameters
        ----------
        message
            The message to delete. If omitted, deletes the original message.
        """

        if not self.app or self.app.config["DONT_REGISTER_WITH_DISCORD"]:
            return

        response = requests.delete(
            self.followup_url(message),
            headers=self.auth_headers
        )
        response.raise_for_status()

    def send(self, response):
        """
        Send a new followup message.

        Parameters
        ----------
        response
            The response to send as a followup message.
        """

        if not self.app or self.app.config["DONT_REGISTER_WITH_DISCORD"]:
            return

        response = Message.from_return_value(response)

        response = requests.post(
            self.followup_url(),
            headers=self.auth_headers,
            **response.dump_multipart()
        )
        response.raise_for_status()
        return response.json()["id"]

    def get_command(self, command_name=None):
        "Get the ID of a command by name."
        if command_name is None:
            return self.command_id
        else:
            try:
                return self.app.discord_commands[command_name].id
            except KeyError:
                raise ValueError(f"Unknown command: {command_name}")

    def overwrite_permissions(self, permissions, command=None):
        """
        Overwrite the permission overwrites for this command.

        Parameters
        ----------
        permissions
            The new list of permission overwrites.
        command
            The name of the command to overwrite permissions for. If omitted,
            overwrites for the invoking command.
        """

        url = (
            f"{self.app.config['DISCORD_BASE_URL']}/"
            f"applications/{self.app.config['DISCORD_CLIENT_ID']}/"
            f"guilds/{self.guild_id}/"
            f"commands/{self.get_command(command)}/permissions"
        )

        data = [permission.dump() for permission in permissions]

        if self.app.config["DONT_REGISTER_WITH_DISCORD"]:
            return

        response = requests.put(url, headers=self.auth_headers, json={
            "permissions": data
        })
        response.raise_for_status()

    def freeze(self):
        "Return a copy of this Context that can be pickled for RQ and Celery."

        app = types.SimpleNamespace()

        CONFIG_KEYS = [
            "DISCORD_BASE_URL",
            "DISCORD_CLIENT_ID",
            "DONT_REGISTER_WITH_DISCORD",
        ]

        app.config = {
            key: self.app.config[key] for key in CONFIG_KEYS
        }

        new_context = Context.from_data(app=app, data=self.data)
        new_context.frozen_auth_headers = self.auth_headers

        return new_context


@dataclass
class AsyncContext(Context):
    """
    Represents the context in which an asynchronous :class:`Command` is
    invoked. Also provides coroutine functions to handle followup messages.

    Users should not need to instantiate this class manually.
    """

    def __post_init__(self):
        if not self.app or self.app.config["DONT_REGISTER_WITH_DISCORD"]:
            return

        self.session = self.app.discord_client_session

    async def edit(self, response, message="@original"):
        """
        Edit an existing message.

        Parameters
        ----------
        response
            The new response to edit the message to.
        message
            The message to edit. If omitted, edits the original message.
        """

        response = Message.from_return_value(response)

        if not self.app or self.app.config["DONT_REGISTER_WITH_DISCORD"]:
            return

        await self.session.patch(
            self.followup_url(message), json=response.dump_followup()
        )

    async def delete(self, message="@original"):
        """
        Delete an existing message.

        Parameters
        ----------
        message
            The message to delete. If omitted, deletes the original message.
        """

        if not self.app or self.app.config["DONT_REGISTER_WITH_DISCORD"]:
            return

        await self.session.delete(self.followup_url(message))

    async def send(self, response):
        """
        Send a new followup message.

        Parameters
        ----------
        response
            The response to send as a followup message.
        """

        response = Message.from_return_value(response)

        if not self.app or self.app.config["DONT_REGISTER_WITH_DISCORD"]:
            return

        async with self.session.post(
            self.followup_url(),
            headers=self.auth_headers,
            **response.dump_multipart()
        ) as response:
            return (await response.json())["id"]

    async def overwrite_permissions(self, permissions, command=None):
        """
        Overwrite the permission overwrites for this command.

        Parameters
        ----------
        permissions
            The new list of permission overwrites.
        command
            The name of the command to overwrite permissions for. If omitted,
            overwrites for the invoking command.
        """

        url = (
            f"{self.app.config['DISCORD_BASE_URL']}/"
            f"applications/{self.app.config['DISCORD_CLIENT_ID']}/"
            f"guilds/{self.guild_id}/"
            f"commands/{self.get_command(command)}/permissions"
        )

        data = [permission.dump() for permission in permissions]

        if not self.app or self.app.config["DONT_REGISTER_WITH_DISCORD"]:
            return

        await self.session.put(url, headers=self.auth_headers, json={
            "permissions": data
        })

    async def close(self):
        """
        Deprecated as of v1.0.2.

        Previously, this closed the AsyncContext's aiohttp ClientSession that
        was used to send followup messages. This is no longer necessary, as
        this library now maintains a single ClientSession for the entire
        application.
        """

        warnings.warn(
            "Deprecated! AsyncContext.close is a no-op. "
            "Since v1.0.2, only one aiohttp ClientSession is created "
            "for all requests to Discord for the app. "
            "Thus, there is no need to close the AsyncContext. ",
            DeprecationWarning
        )
