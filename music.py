import asyncio
import traceback
import discord
from discord.ext import commands
import yt_dlp

YDL_OPTIONS = {
    "format": "bestaudio[ext=webm]/bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch",
    "source_address": "0.0.0.0",
    "extract_flat": False,
    "http_headers": {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    },
}


FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}


class Song:
    def __init__(self, title, url, stream_url, duration, requester):
        self.title = title
        self.url = url
        self.stream_url = stream_url
        self.duration = duration
        self.requester = requester

    @staticmethod
    async def from_query(query, requester, loop=None):
        loop = loop or asyncio.get_event_loop()
        with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
            info = await loop.run_in_executor(None, lambda: ydl.extract_info(query, download=False))

        if info is None:
            raise Exception("Could not find any results.")

        if "entries" in info:
            if not info["entries"]:
                raise Exception("No results found.")
            info = info["entries"][0]

        return Song(
            title=info.get("title", "Unknown"),
            url=info.get("webpage_url", query),
            stream_url=info["url"],
            duration=info.get("duration", 0),
            requester=requester,
        )

    def format_duration(self):
        if not self.duration:
            return "Live"
        m, s = divmod(int(self.duration), 60)
        h, m = divmod(m, 60)
        if h:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"


class GuildMusicState:
    def __init__(self):
        self.queue = []
        self.current = None
        self.volume = 0.5


def setup_music_commands(bot, config):
    cmd_names = config.get("commands", {})
    states = {}

    def get_state(guild_id):
        if guild_id not in states:
            states[guild_id] = GuildMusicState()
        return states[guild_id]

    async def ensure_voice(ctx):
        if not ctx.author.voice:
            await ctx.send("You need to be in a voice channel!")
            return None

        channel = ctx.author.voice.channel
        vc = ctx.guild.voice_client

        try:
            if vc is None:
                vc = await channel.connect()
            elif vc.channel != channel:
                await vc.move_to(channel)
        except Exception as e:
            await ctx.send(f"Failed to connect: {e}")
            print(f"[VOICE ERROR] {e}")
            traceback.print_exc()
            return None

        if not vc or not vc.is_connected():
            await ctx.send("Failed to connect to voice channel!")
            return None

        return get_state(ctx.guild.id)

    def play_next(guild_id):
        state = get_state(guild_id)
        guild = bot.get_guild(guild_id)
        if guild is None:
            return
        vc = guild.voice_client

        if not state.queue:
            state.current = None
            if vc and vc.is_connected():
                asyncio.run_coroutine_threadsafe(auto_disconnect(guild_id), bot.loop)
            return

        state.current = state.queue.pop(0)
        if not vc or not vc.is_connected():
            state.current = None
            state.queue.clear()
            return

        source = discord.PCMVolumeTransformer(
            discord.FFmpegPCMAudio(state.current.stream_url, **FFMPEG_OPTIONS),
            volume=state.volume,
        )

        def after_play(error):
            if error:
                print(f"[PLAY ERROR] {error}")
            play_next(guild_id)

        vc.play(source, after=after_play)

    async def auto_disconnect(guild_id):
        await asyncio.sleep(120)
        state = get_state(guild_id)
        guild = bot.get_guild(guild_id)
        if guild is None:
            return
        vc = guild.voice_client
        if vc and vc.is_connected() and not vc.is_playing():
            await vc.disconnect()

    @bot.command(name=cmd_names.get("play", "play"))
    async def play(ctx, *, query: str):
        """Play a song from YouTube (URL or search)"""
        state = await ensure_voice(ctx)
        if not state:
            return
        try:
            async with ctx.typing():
                song = await Song.from_query(query, ctx.author, bot.loop)
        except Exception as e:
            await ctx.send(f"Error: {e}")
            traceback.print_exc()
            return

        vc = ctx.guild.voice_client
        if not vc or not vc.is_connected():
            await ctx.send("Lost voice connection. Try again!")
            return

        if vc.is_playing() or state.current:
            state.queue.append(song)
            embed = discord.Embed(
                title="Added to Queue",
                description=f"[{song.title}]({song.url})",
                color=discord.Color.green(),
            )
            embed.add_field(name="Duration", value=song.format_duration())
            embed.add_field(name="Position", value=str(len(state.queue)))
            embed.set_footer(text=f"Requested by {ctx.author.display_name}")
            await ctx.send(embed=embed)
        else:
            state.current = song
            source = discord.PCMVolumeTransformer(
                discord.FFmpegPCMAudio(song.stream_url, **FFMPEG_OPTIONS),
                volume=state.volume,
            )

            def after_play(error):
                if error:
                    print(f"[PLAY ERROR] {error}")
                play_next(ctx.guild.id)

            vc.play(source, after=after_play)
            embed = discord.Embed(
                title="Now Playing",
                description=f"[{song.title}]({song.url})",
                color=discord.Color.blue(),
            )
            embed.add_field(name="Duration", value=song.format_duration())
            embed.set_footer(text=f"Requested by {ctx.author.display_name}")
            await ctx.send(embed=embed)

    @bot.command(name=cmd_names.get("skip", "skip"))
    async def skip(ctx):
        """Skip the current song"""
        vc = ctx.guild.voice_client
        if not vc or not vc.is_playing():
            await ctx.send("Nothing is playing!")
            return
        vc.stop()
        await ctx.send("Skipped!")

    @bot.command(name=cmd_names.get("stop", "stop"))
    async def stop(ctx):
        """Stop playback and clear the queue"""
        vc = ctx.guild.voice_client
        if not vc:
            await ctx.send("Not connected!")
            return
        state = get_state(ctx.guild.id)
        state.queue.clear()
        state.current = None
        vc.stop()
        await ctx.send("Stopped and cleared the queue.")

    @bot.command(name=cmd_names.get("pause", "pause"))
    async def pause(ctx):
        """Pause the current song"""
        vc = ctx.guild.voice_client
        if vc and vc.is_playing():
            vc.pause()
            await ctx.send("Paused.")
        else:
            await ctx.send("Nothing is playing!")

    @bot.command(name=cmd_names.get("resume", "resume"))
    async def resume(ctx):
        """Resume the paused song"""
        vc = ctx.guild.voice_client
        if vc and vc.is_paused():
            vc.resume()
            await ctx.send("Resumed.")
        else:
            await ctx.send("Nothing is paused!")

    @bot.command(name=cmd_names.get("queue", "queue"))
    async def queue(ctx):
        """Show the current queue"""
        state = get_state(ctx.guild.id)
        if not state.current and not state.queue:
            await ctx.send("Queue is empty!")
            return
        embed = discord.Embed(title="Music Queue", color=discord.Color.purple())
        if state.current:
            embed.add_field(
                name="Now Playing",
                value=f"[{state.current.title}]({state.current.url}) [{state.current.format_duration()}]",
                inline=False,
            )
        if state.queue:
            queue_text = ""
            for i, song in enumerate(state.queue[:10], 1):
                queue_text += f"`{i}.` [{song.title}]({song.url}) [{song.format_duration()}]\n"
            if len(state.queue) > 10:
                queue_text += f"\n... and {len(state.queue) - 10} more"
            embed.add_field(name="Up Next", value=queue_text, inline=False)
        embed.set_footer(text=f"{len(state.queue)} song(s) in queue")
        await ctx.send(embed=embed)

    @bot.command(name=cmd_names.get("nowplaying", "nowplaying"))
    async def nowplaying(ctx):
        """Show the currently playing song"""
        state = get_state(ctx.guild.id)
        if not state.current:
            await ctx.send("Nothing is playing!")
            return
        embed = discord.Embed(
            title="Now Playing",
            description=f"[{state.current.title}]({state.current.url})",
            color=discord.Color.blue(),
        )
        embed.add_field(name="Duration", value=state.current.format_duration())
        embed.add_field(name="Volume", value=f"{int(state.volume * 100)}%")
        embed.set_footer(text=f"Requested by {state.current.requester.display_name}")
        await ctx.send(embed=embed)

    @bot.command(name=cmd_names.get("volume", "volume"))
    async def volume(ctx, vol: int):
        """Set volume (0-100)"""
        if not 0 <= vol <= 100:
            await ctx.send("Volume must be between 0 and 100!")
            return
        state = get_state(ctx.guild.id)
        state.volume = vol / 100
        vc = ctx.guild.voice_client
        if vc and vc.source:
            vc.source.volume = state.volume
        await ctx.send(f"Volume set to {vol}%")

    @bot.command(name=cmd_names.get("clear", "clear"))
    async def clear(ctx):
        """Clear the queue"""
        state = get_state(ctx.guild.id)
        state.queue.clear()
        await ctx.send("Queue cleared!")

    @bot.command(name=cmd_names.get("leave", "leave"))
    async def leave(ctx):
        """Disconnect the bot from voice"""
        vc = ctx.guild.voice_client
        if vc and vc.is_connected():
            state = get_state(ctx.guild.id)
            state.queue.clear()
            state.current = None
            await vc.disconnect()
            await ctx.send("Disconnected!")
        else:
            await ctx.send("Not connected!")
