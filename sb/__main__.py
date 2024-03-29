import collections
import itertools
import json
import re
import sqlite3
import time
from datetime import datetime, timedelta
from typing import List, Optional, Union

import discord
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from discord.ext import commands

config = {}
with open("settings.json", "r") as f:
    config = json.load(f)

database = sqlite3.connect(config["database"], isolation_level=None, timeout=10.0)
database.row_factory = sqlite3.Row

intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix="sb ", intents=intents, help_command=None)
bot.add_check(
    lambda ctx: ctx.author.guild_permissions.manage_messages or ctx.channel.name == "bot-stuff"
)


@bot.command(name="help")
async def _help(ctx: commands.Context):
    await ctx.send(
        """
Welcome to Big Sister's Surveillance Query Interface!

__**Channels & Categories**__
*How active has the server been?*
`sb server <day/week/month/all =all>`
*How active have these categories been?*
`sb cat <day/week/month/all> [category name or part of it]`
*How active have these channels been?*
`sb chan <day/week/month/all> <channels...>`
*How active have these channels been, but as a graph?*
`sb graph <channels...>`
Which roles are most present in these channels?
`sb roles <day/week/month/all> <channels...>`

__**Users**__
*Who has been active in these channels?*
`sb voters <channels...>`
*Who has posted a phrase most frequently?*
`sb wordcount <phrase>`
*How many posts has someone made?*
`sb postcount <users...>`
*Who are the most active users?*
`sb leaderboard [day/week/month/all =all] [number of users =10]`
*How many modlogs do these users have?*
`sb modlogs <users...>`
*Which mod is the worst?*
`sb modscoreboard`
"""
    )


async def paged_send(ctx: commands.Context, text: str):
    "Reply and respect discord's length stuff"

    blocks = [""]
    for line in text.split("\n"):
        if len(line) + len(blocks[-1]) < 2000:
            blocks[-1] += "\n" + line
        else:
            blocks.append(line)

    for block in blocks:
        await ctx.send(block)


def select(sql: str, params: dict) -> List[sqlite3.Row]:
    "Do a SELECT statement and print it"

    now = time.monotonic()
    rows = database.execute(sql, params).fetchall()
    delta = timedelta(seconds=(time.monotonic() - now))

    print(re.sub(r"\s+", " ", sql), params, delta, sep="\n")
    return rows


def sql_time(timedesc: str) -> str:
    "turn a human writable time description into something sqlite likes"
    if timedesc == "week":
        return "-7 days"
    elif timedesc == "day":
        return "-1 days"
    elif timedesc == "month":
        return "-28 days"

    raise ValueError(f"Invalid argument to sql_time: {timedesc}")


def is_bot(member: discord.Member) -> bool:
    "Determine if a user is a bot account via roles."

    return member.bot and any([r for r in member.roles if r.name == "Bots"])


@bot.command()
async def postcount(ctx: commands.Context, users: commands.Greedy[Union[discord.Member, int]]):
    "How many posts have these users made?"

    reply = ""

    for user in users:
        # if we just got an ID instead of a ping, use that
        user_id = getattr(user, "id", user)
        user_name = bot.get_user(user_id).name

        count = select("SELECT count(*) FROM messages WHERE author=:uid;", {"uid": user_id})[0][0]

        reply += f"{user_name} postcount: {count}\n"

    await paged_send(ctx, reply)


@bot.command()
async def wordcount(ctx: commands.Context, *, phrase: str):
    "Who has said this phrase most?"

    if " " in phrase:
        await ctx.send("One word at a time please")
    elif "@" in phrase:
        await ctx.send("No pings")
    elif "_" in phrase or "%" in phrase:
        await ctx.send("No wildcards")
    else:
        rows = select(
            """SELECT author, count(author) FROM messages WHERE clean_content like :match
            AND channelid != 622383698259738654 AND channelid != 588461846508470285
            AND channelid != 611249002842947585 AND channelid != 554050936218320926
            GROUP BY author ORDER BY count(author) DESC LIMIT :count;""",
            {"match": f"%{phrase}%", "count": 15},
        )

        rowno = 1
        reply = f"Top 10 '{phrase}'ers: \n"
        for row in rows:
            user = ctx.guild.get_member(row[0])
            if user is not None and not is_bot(user):
                reply += f"{rowno}. {user}: {row[1]} '{phrase}'s\n"
                rowno += 1
            if rowno == 11:
                break

        await paged_send(ctx, reply)


@bot.command()
async def cat(
    ctx: commands.Context, timedesc: str, selector: Optional[Union[discord.CategoryChannel, str]],
):
    "What are the most active channels in these categories?"

    look_at = []
    if not selector:
        look_at = ctx.channel.category.channels
    elif isinstance(selector, discord.CategoryChannel):
        look_at = selector.channels
    elif isinstance(selector, str):
        look_at = [
            channel
            for channel in ctx.guild.channels
            if channel.category and selector in channel.category.name.casefold()
        ]

    look_at = [channel for channel in look_at if channel.permissions_for(ctx.author).read_messages]

    if not look_at:
        ctx.send(f"No channels found for '{selector}'")
        return

    channels = []

    for channel in look_at:
        row = tuple()
        if timedesc == "all":
            row = select(
                """SELECT count(*), count(distinct author) FROM messages
                WHERE channelid=:channelid""",
                {"channelid": channel.id},
            )[0]
        else:
            row = select(
                """SELECT count(*), count(distinct author) FROM messages
                WHERE channelid=:channelid AND created_at >= datetime('now', :ago)""",
                {"channelid": channel.id, "ago": sql_time(timedesc)},
            )[0]
        channels.append((channel.name, row[0], row[1]))

    reply = ""

    for channel in sorted(channels, key=lambda tup: tup[1], reverse=True):
        reply += f"{channel[0]}: {channel[1]} messages from {channel[2]} users\n"

    await paged_send(ctx, reply)


@bot.command(name="chan")
async def chan(
    ctx: commands.Context, timedesc: str, look_at: commands.Greedy[discord.TextChannel],
):
    "How active have these channels been?"

    channels = []
    reply = ""

    look_at = [channel for channel in look_at if channel.permissions_for(ctx.author).read_messages]

    for channel in look_at:
        row = tuple()
        if timedesc == "all":
            row = select(
                """SELECT count(*), count(distinct author) FROM messages
                WHERE channelid=:channelid""",
                {"channelid": channel.id},
            )[0]
        else:
            row = select(
                """SELECT count(*), count(distinct author) FROM messages
                WHERE channelid=:channelid AND created_at >= datetime('now', :ago)""",
                {"channelid": channel.id, "ago": sql_time(timedesc)},
            )[0]

        channels.append((channel.name, row[0], row[1]))

    for channel in sorted(channels, key=lambda tup: tup[1], reverse=True):
        reply += f"{channel[0]}: {channel[1]} messages from {channel[2]} users\n"

    await paged_send(ctx, reply)


@bot.command()
async def graph(ctx: commands.Context, look_at: commands.Greedy[discord.TextChannel]):
    "How active have these channels been, but as a graph?"

    look_at = [channel for channel in look_at if channel.permissions_for(ctx.author).read_messages]

    for channel in look_at:
        postdates = []
        postcounts = []
        rows = select(
            """SELECT strftime('%Y-%m-%d', created_at) as valDay, count(id) postcount
            FROM messages where channelname = :channelname and created_at >= datetime('now', :ago)
            GROUP BY valDay
            ORDER BY created_at;""",
            {"channelname": channel.name, "ago": sql_time("month")},
        )
        for row in rows:
            postdates.append(datetime.strptime(row[0], "%Y-%m-%d").date())
            postcounts.append(row[1])

        fig, axes = plt.subplots()
        axes.plot(postdates, postcounts)
        axes.set(xlabel="Date", ylabel="Postcount", title=channel.name)
        locator = mdates.AutoDateLocator(minticks=10, maxticks=30)
        formatter = mdates.ConciseDateFormatter(locator)
        axes.xaxis.set_major_locator(locator)
        axes.xaxis.set_major_formatter(formatter)
        axes.grid(color="b", ls="-.", lw=0.25)
        fig.autofmt_xdate(bottom=0.2, rotation=45, ha="right", which="major")
        fig.savefig("chart.png")
        await ctx.send(file=discord.File("chart.png"))


@bot.command()
async def server(ctx: commands.Context, timedesc: str = "all"):
    "How active has the server been?"

    row = tuple()
    if timedesc == "all":
        row = select("SELECT count(*), count(distinct author) FROM messages", {})[0]
    else:
        row = select(
            """SELECT count(*), count(distinct author) FROM messages
                WHERE created_at >= datetime('now', :ago)""",
            {"ago": sql_time(timedesc)},
        )[0]
    await ctx.send(f"{ctx.guild.name}: {row[0]:n} messages from {row[1]} users")


@bot.command()
async def roles(
    ctx: commands.Context, timedesc: str, look_at: commands.Greedy[discord.TextChannel],
):
    "Which roles are most present in these channels?"

    look_at = [channel for channel in look_at if channel.permissions_for(ctx.author).read_messages]

    for channel in look_at:
        user_ids = []
        if timedesc == "all":
            user_ids = select(
                "SELECT DISTINCT author FROM messages WHERE channelid = :channelid",
                {"channelid": channel.id},
            )
        else:
            user_ids = select(
                """SELECT DISTINCT author FROM messages
                    WHERE channelid = :channelid
                    AND created_at >= datetime('now', :ago)""",
                {"channelid": channel.id, "ago": sql_time(timedesc)},
            )

        count = collections.Counter()
        members = [ctx.guild.get_member(i[0]) for i in user_ids]
        members = [member for member in members if member]
        for member in members:
            count.update(member.roles)

        await paged_send(
            ctx,
            "\n".join(
                [
                    f"{num} {r.name}"
                    for r, num in sorted(count.items(), key=lambda tup: tup[1], reverse=True)
                    if not r.name == "@everyone"
                ]
            ),
        )


@bot.command(name="voters")
async def _voters(
    ctx: commands.Context, look_at: commands.Greedy[discord.TextChannel],
):
    "Who has been active in these channels?"

    reply = (
        "*Numbers mean:*\n"
        + "*1) Number of weeks in the last month where user was more active than the mean*\n"
        + "*2) Average number of posts in these weeks*\n\n"
    )

    look_at = [channel for channel in look_at if channel.permissions_for(ctx.author).read_messages]

    for channel in look_at:
        reply += f"{channel.mention}:\n"

        found_users = []

        # for every week in the last month:
        for veryago, lessago in (
            ("-7 days", "-0 days"),
            ("-14 days", "-7 days"),
            ("-21 days", "-14 days"),
            ("-28 days", "-21 days"),
        ):
            # determine average posts per user
            average = select(
                """SELECT count(*)/count(distinct author) FROM messages
                WHERE channelid = :channelid
                AND created_at >= datetime("now", :veryago)
                AND created_at <= datetime("now", :lessago)""",
                {"channelid": channel.id, "veryago": veryago, "lessago": lessago},
            )[0][0]

            # get (user_id, post_count) for everyone "active" (above mean)
            users_in_upper_half = select(
                """SELECT author, count(id) as num_messages FROM messages
                WHERE channelid = :channelid
                AND created_at >= datetime("now", :veryago)
                AND created_at <= datetime("now", :lessago)
                GROUP BY author
                HAVING num_messages > :average
                ORDER BY num_messages DESC""",
                {
                    "channelid": channel.id,
                    "veryago": veryago,
                    "lessago": lessago,
                    "average": average,
                },
            )
            found_users.extend(users_in_upper_half)

        # found_users now contains active users for every week like this:
        # [(user_a, count_a_1), (user_b, count_b_1), (user_b, count_b_1)]
        # we want to group it by user, like this
        # [(user_a, count_a_1), ((user_b, count_b_1), (user_b, count_b_1))]
        user_weeks = []
        by_user = lambda tup: tup[0]
        for _, group in itertools.groupby(sorted(found_users, key=by_user), key=by_user):
            user_weeks.append(list(group))

        calculate_average_per_week = lambda weeks: sum([week[1] for week in weeks]) // len(weeks)

        # sort our results for presentation
        user_weeks = sorted(
            user_weeks,
            key=lambda weeks: (
                len(weeks),
                calculate_average_per_week(weeks),  # pylint: disable=cell-var-from-loop
            ),
            reverse=True,
        )

        for weeks in user_weeks:
            reply += f"**{len(weeks)}, {calculate_average_per_week(weeks)}** "
            reply += f"{bot.get_user(weeks[0][0])}\n"

        reply += "\n"

    await paged_send(ctx, reply)


@bot.command()
@commands.has_guild_permissions(manage_messages=True)
async def modlogs(ctx: commands.Context, users: commands.Greedy[discord.User]):
    "How many modlogs do these users have?"

    reply = f"{ctx.author.mention}\n\n"

    for user in users:
        row = select(
            """SELECT COUNT(id) FROM modlogs
            WHERE user=:user AND created_at >= datetime('now', :ago)""",
            {"user": user.id, "ago": "-6 months"},
        )[0]

        reply += f"{user.mention} has {row[0]} modlogs\n"

    await paged_send(bot.get_channel(int(config["private_channel"])), reply)


@bot.command()
@commands.has_guild_permissions(manage_messages=True)
async def modscoreboard(ctx: commands.Context, timedesc: str = "all"):
    "Which mod is the worst?"
    rowno = 1
    rows = []
    if timedesc == "all":
        rows = select(
            """SELECT author, count(author) FROM modlogs
            GROUP BY author ORDER BY count(id) DESC""",
            {},
        )
    else:
        rows = select(
            """SELECT author, count(author) FROM modlogs
            WHERE created_at >= datetime('now', :ago)
            GROUP BY author ORDER BY count(id) DESC""",
            {"ago": sql_time(timedesc)},
        )

    reply = f"Top {len(rows)} punishers: \n"
    for row in rows:
        user = bot.get_user(row[0])
        if user is not None:
            reply += f"{rowno}. {user}: {row[1]} punishments\n"
            rowno += 1

    await paged_send(ctx, reply)


@bot.command()
async def leaderboard(ctx: commands.Context, timedesc: str = "all", count: int = 10):
    "Who are the most active users?"

    rowno = 1
    rows = []
    if timedesc == "all":
        rows = select(
            """SELECT author, COUNT(id) FROM messages
            GROUP BY author ORDER BY count(id) DESC limit :count;""",
            {"count": count},
        )
    else:
        rows = select(
            """SELECT author, COUNT(id) FROM messages
            WHERE created_at >= datetime('now', :ago)
            GROUP BY author ORDER BY count(id) DESC limit :count;""",
            {"ago": sql_time(timedesc), "count": count},
        )

    reply = f"Top {count} posters:\n"

    for row in rows:
        user = ctx.guild.get_member(row[0])
        if user is not None and not is_bot(user):
            reply += f"{rowno}. {user}: {row[1]} Messages\n"
            rowno += 1

    await paged_send(ctx, reply)


@bot.event
async def on_message(msg: discord.Message):
    "insert messages into database and run commands if applicable"
    if not msg.guild.id == int(config["server"]):
        return

    database.execute(
        """INSERT INTO
        messages(id, author, channelid, channelname, guildid, clean_content, created_at)
        VALUES(:id, :author, :channelid, :channelname, :guildid, :clean_content, :created_at)""",
        {
            "id": msg.id,
            "author": msg.author.id,
            "channelid": msg.channel.id,
            "channelname": msg.channel.name,
            "guildid": msg.guild.id,
            "clean_content": msg.clean_content,
            "created_at": msg.created_at,
        },
    )

    if (
        msg.content.startswith("!warn ") or msg.content.startswith("!mute ")
    ) and msg.guild.get_member(msg.author.id).guild_permissions.manage_messages:
        await add_modlog(msg)

    await bot.process_commands(msg)


@bot.event
async def on_ready():
    "say hello"
    print(f"Logged in as {bot.user} ({bot.user.id})")


async def add_modlog(msg: discord.Message):
    "Check if something is a warn/mute and add it to the database if so"

    command, user = re.search(r"(.mute|.warn)\s+(?:<@!?)?(\d+)", msg.content).groups()

    modlog_type = None
    if command == ".mute":
        modlog_type = 1
    elif command == ".warn":
        modlog_type = 0

    if msg.guild.get_member(int(user)):
        database.execute(
            """INSERT INTO
            modlogs(id, author, channelid, channelname, guildid, clean_content, created_at, user,
            type)
            VALUES(:id, :author, :channelid, :channelname, :guildid, :clean_content, :created_at,
            :user, :type)""",
            {
                "id": msg.id,
                "author": msg.author.id,
                "channelid": msg.channel.id,
                "channelname": msg.channel.name,
                "guildid": msg.guild.id,
                "clean_content": msg.clean_content,
                "created_at": msg.created_at,
                "user": user,
                "type": modlog_type,
            },
        )

        num_modlogs = select(
            """SELECT COUNT(id) FROM modlogs
            WHERE user=:user AND created_at >= datetime('now', :ago)""",
            {"user": user, "ago": "-6 months"},
        )[0][0]
        if num_modlogs % 5 == 0:
            logs = bot.get_channel(int(config["private_channel"]))
            await logs.send(f"<@&{config['notify_role']}> <@{user}> has {num_modlogs} modlogs")


def main():
    "entry point"
    bot.run(config["token"])


if __name__ == "__main__":
    main()
