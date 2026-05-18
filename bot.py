import json
import asyncio
import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

import sys

if not discord.opus.is_loaded():
    if sys.platform == "win32":
        discord.opus.load_opus(os.path.join(os.path.dirname(os.path.abspath(__file__)), "libopus-0.dll"))
    else:
        for lib in ("libopus.so.0", "libopus.so"):
            try:
                discord.opus.load_opus(lib)
                break
            except OSError:
                continue


def load_config():
    with open("config.json", "r", encoding="utf-8") as f:
        return json.load(f)


config = load_config()

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix=config.get("prefix", "!"), intents=intents)


@bot.event
async def on_ready():
    print(f"Bot is ready! Logged in as {bot.user}")
    print(f"Prefix: {config.get('prefix', '!')}")
    print(f"Servers: {len(bot.guilds)}")


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"Missing argument: `{error.param.name}`")
        return
    await ctx.send(f"Error: {error}")
    print(f"[ERROR] {ctx.command}: {error}")


async def main():
    from music import setup_music_commands
    setup_music_commands(bot, config)
    token = os.getenv("BOT_TOKEN")
    if not token:
        print("ERROR: BOT_TOKEN not found in .env file!")
        print("Create a .env file with: BOT_TOKEN=your_token_here")
        return
    await bot.start(token)


if __name__ == "__main__":
    asyncio.run(main())
