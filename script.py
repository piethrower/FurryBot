#!/usr/bin/python3

import discord
import secrets
import blocklist
import re
import requests

client = discord.Client()
TOKEN = secrets.token

url = "https://e621.net/posts.json"
headers = {
    "User-Agent": "DiscordFurryBot V0.1",
}

@client.event
async def on_ready():
    print('We have logged in as {0.user}'.format(client))


@client.event
async def on_message(message):
    if message.author == client.user:
        return

    channel = message.channel

    message_content = message.clean_content.lower()

    if message_content.startswith("!~ "):

        params = {
            "limit": 1,
            "tags": message_content[3:]
        }

        if not channel.is_nsfw():
            params["tags"] += " rating:s"

        for tag in blocklist.tags:
            params["tags"] += " -" + tag

        r = requests.get(url, params=params, headers=headers)

        print(r.url)

        if r.status_code != 200:
            await channel.send("Error: recieved status code: " + str(r.status_code))
            return

        response = r.json()

        posts = response["posts"]

        if len(posts) < 1:
            await channel.send("no images found")
            return

        image_url = posts[0]["file"]["url"]
        image_description = posts[0]["description"]

        if len(image_description) < 500:
            await channel.send(image_description)
        await channel.send(image_url)


client.run(TOKEN)
