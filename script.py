#!/usr/bin/python

import secrets
import asyncio
import signal
import sys
import requests
import discord
import blocklist
import logging

# TODO:
# graceful exit
# add way to look at image data (post artist?)
# tag search
# rate limiting


intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.reactions = True

CLIENT = discord.Client(intents=intents)

# enable logging
logger = logging.getLogger('discord')
logger.setLevel(logging.INFO)
handler = logging.FileHandler(filename="discord.log", encoding="utf-8", mode="w")
dt_fmt = '%Y-%m-%d %H:%M:%S'
formatter = logging.Formatter('[{asctime}] [{levelname:<8}] {name}: {message}', dt_fmt, style='{')
handler.setFormatter(formatter)
logger.addHandler(handler)


MAX_IMAGES = 32

STATUS = "!~ tags"

BASE_URL = "https://e621.net/"
HEADERS = {
    # If you are running this yourself change the User_Agent to include your main e621 username
    "User-Agent": "DiscordFurryBot V1.2",
}

MAX_CACHE_SIZE = 32
cache = []


class HTTP404Exception(Exception):
    pass


class ButtonRow(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    active_style = discord.ButtonStyle.blurple
    inactive_style = discord.ButtonStyle.grey

    @discord.ui.button(style=inactive_style, label="First", disabled=True, custom_id="first_button")
    async def first_image(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await change_image(interaction.message, to_left=True, to_end=True)

    @discord.ui.button(style=inactive_style, label="Prev", emoji="⬅️", disabled=True, custom_id="prev_button")
    async def prev_image(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await change_image(interaction.message, to_left=True)

    @discord.ui.button(style=active_style, label="Next", emoji="➡️", disabled=False, custom_id="next_button")
    async def next_image(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await change_image(interaction.message)

    @discord.ui.button(style=active_style, label="Last", disabled=False, custom_id="last_button")
    async def last_image(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await change_image(interaction.message, to_end=True)

    @discord.ui.button(style=discord.ButtonStyle.red, label="Delete", disabled=False, custom_id="delete_message")
    async def delete_message(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.message.delete()
        await interaction.response.send_message("Message deleted", ephemeral=True)


def clamp(num, min_num, max_num):
    return max(min(num, max_num), min_num)


def pos_in_cache(message):
    i = 0
    while i < len(cache):
        if message == cache[i]["message"]:
            return i
        i += 1
    return -1


# returns false if any tag is on the blocklist
def check_post(post):
    tags = post["tags"]["general"]
    for tag in tags:
        if tag in blocklist.general_tags:
            return False
    if post["score"]["total"] < 0:
        return False
    return True


def get_posts(tags="", is_nsfw=False):
    params = {
        "limit": MAX_IMAGES,
        "tags": tags
    }

    params["tags"] += " -huge_filesize -flash score:>=0"

    if not is_nsfw:
        params["tags"] += " rating:s status:active tagcount:>15"
        for tag in blocklist.nsfw_only:
            params["tags"] += " -" + tag

    response = requests.get(f"{BASE_URL}posts.json", params=params, headers=HEADERS,
                            auth=(secrets.login, secrets.api_key))

    if response.status_code != 200:
        HTTP404Exception(str(response.status_code))

    response_json = response.json()

    posts = response_json["posts"]

    return posts


async def disable_buttons(post):
    message = post["message"]
    view = post["view"]
    for button in view.children:
        button.disabled = True
    await message.edit(view=view)


@CLIENT.event
async def on_ready():
    print(f"We have logged in as {CLIENT.user}")
    await CLIENT.change_presence(activity=discord.Game(STATUS))

@CLIENT.event
async def on_message_delete(message):
    if message.author != CLIENT.user:
        return
    cache_pos = pos_in_cache(message)
    if cache_pos == -1:
        return
    cache.pop(cache_pos)

@CLIENT.event
async def on_message(user_message):
    author = user_message.author
    if author == CLIENT.user:
        return

    channel = user_message.channel

    message_content = user_message.clean_content.lower()

    if message_content.startswith("!~ "):

        tags = message_content[3:]

        is_nsfw = channel.is_nsfw()

        try:
            posts = get_posts(tags, is_nsfw)
        except HTTP404Exception:
            await channel.send(f"Error: recieved status code: {response.status_code}")
            return

        filtered = []
        for post in posts:
            if check_post(post):
                filtered.append(post)
        posts = filtered

        if len(posts) == 0:
            await channel.send("No images found")
            return

        post = posts[0]

        view = ButtonRow()
        embed = discord.Embed(title=tags, url=f"{BASE_URL}posts/{post['id']}")
        # embed.description = post["description"]
        embed.set_image(url=post["file"]["url"])
        embed.set_footer(text=f"Image 1 of {len(posts)}")
        embed.set_author(name=author, icon_url=author.avatar.url)
        if is_nsfw:
            embed.color = discord.Color.brand_red()
        else:
            embed.color = discord.Color.brand_green()
        bot_message = await channel.send(embed=embed, view=view)

        cache.append({"message": bot_message, "pos": 0,
                     "posts": posts, "view": view, "embed": embed})
        if len(cache) > MAX_CACHE_SIZE:
            old_post = cache.pop(0)
            await disable_buttons(old_post)

        return


async def change_image(message, to_left=False, to_end=False):
    cache_pos = pos_in_cache(message)
    if cache_pos == -1:
        return
    item = cache[cache_pos]
    posts = item["posts"]
    pos = item["pos"]
    view = item["view"]
    embed = item["embed"]

    if to_end:
        if to_left:
            pos = 0
        else:
            pos = len(posts) - 1
    else:
        if to_left:
            pos -= 1
        else:
            pos += 1
        pos = clamp(pos, 0, len(posts) - 1)

    for button in view.children:
        button.disabled = False

    cache[cache_pos]["pos"] = pos

    if pos == 0:
        for button in view.children:
            if button.custom_id in ("first_button", "prev_button"):
                button.disabled = True
    elif pos == len(posts) - 1:
        for button in view.children:
            if button.custom_id in ("next_button", "last_button"):
                button.disabled = True

    post = posts[pos]

    embed.set_image(url=post["file"]["url"])
    embed.set_footer(text=f"Image {pos+1} of {len(posts)}")
    embed.url = f"{BASE_URL}posts/{post['id']}"
    # embed.description = post["description"]

    await message.edit(embed=embed, view=view)


async def cleanup():
    print("\nCleaning up")
    for item in cache:
        await disable_buttons(item)


def terminate_process(signum, frame):
    sys.exit()


signal.signal(signal.SIGTERM, terminate_process)


loop = asyncio.get_event_loop()

try:
    loop.run_until_complete(CLIENT.start(secrets.token))
except (KeyboardInterrupt, SystemExit):
    loop.run_until_complete(cleanup())
    loop.run_until_complete(CLIENT.close())
    # cancel all tasks lingering
finally:
    loop.close()
    print("Exiting")
