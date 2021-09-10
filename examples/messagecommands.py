import os
import sys

import json

from flask import Flask

# This is just here for the sake of examples testing
# to make sure that the imports work
# (you don't actually need it in your code)
sys.path.insert(1, ".")

from flask_discord_interactions import DiscordInteractions  # noqa: E402
from flask_discord_interactions.context import ApplicationCommandType


app = Flask(__name__)
discord = DiscordInteractions(app)

# Find these in your Discord Developer Portal, store them as environment vars
app.config["DISCORD_CLIENT_ID"] = os.environ["DISCORD_CLIENT_ID"]
app.config["DISCORD_PUBLIC_KEY"] = os.environ["DISCORD_PUBLIC_KEY"]
app.config["DISCORD_CLIENT_SECRET"] = os.environ["DISCORD_CLIENT_SECRET"]


# Clear any existing global commands
discord.update_commands()


# Simple command to change a message
@discord.command(name="Make it bold", type=ApplicationCommandType.MESSAGE)
def boldMessage(ctx, message):
    return f"**{message.content}**"


# This is the URL that your app will listen for Discord Interactions on
# Put this into the developer portal
discord.set_route("/interactions")


# Register application commands with this
# (omit guild_id parameter to register global commands,
# but note that these can take up to 1 hour to be registered)
# This also removes old/unused commands
discord.update_commands(guild_id=os.environ["TESTING_GUILD"])


if __name__ == '__main__':
    app.run()
