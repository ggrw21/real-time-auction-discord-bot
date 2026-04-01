import discord
from discord import app_commands
from discord.ext import commands
from config import token, emojis
import asyncio
from datetime import datetime
import sqlite3

bot = commands.Bot(command_prefix="!", intents=discord.Intents.all())

def init_db():
    conn = sqlite3.connect('records.db')
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS auctions (
        auctionID INTEGER PRIMARY KEY AUTOINCREMENT,
        channel INTEGER,
        breakgoal INTEGER,
        totalBids INTEGER,
        enddatetime INTEGER,
        active INTEGER
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS items (
        itemID INTEGER PRIMARY KEY AUTOINCREMENT,
        auctionID INTEGER,
        itemName TEXT,
        emoji TEXT,
        highestBid INTEGER DEFAULT 0,
        highestBidder INTEGER DEFAULT 0,
        endTime INTEGER
    )
    """)

    conn.commit()
    conn.close()

@bot.event
async def on_ready():
    print('Bot is ready!')
    init_db()
    try:
        await bot.change_presence(
        activity=discord.Game(name="Made by daybroken")
    )
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} commands")
    except Exception as e:
        print(e)
    bot.loop.create_task(check_auctions())

# Background task to check if any auctions have ended
async def check_auctions():
    while True:
        await asyncio.sleep(3)

        # Connect to database
        conn = sqlite3.connect('records.db')
        cursor = conn.cursor()

        # Get active auctions
        cursor.execute('SELECT * FROM auctions WHERE active = 1')
        auctions = cursor.fetchall()

        # Check each auction if it has ended
        for auction in auctions:
            # Assuming auction[4] is the end time
            end_time = auction[4]
            current_time = int(datetime.now().timestamp())
            if current_time > end_time:
                cursor.execute('UPDATE auctions SET active = 0 WHERE auctionID = ?', (auction[0],))
                conn.commit()

                auction_results = ""
                cursor.execute('SELECT * FROM items WHERE auctionID = ?', (auction[0],))
                items = cursor.fetchall()

                for item in items:
                    auction_results += f"{item[5]} {item[2]} - ${item[3]} - <@{item[4]}>\n"

                channel = bot.get_channel(auction[1]) 
                await channel.send(f"**AUCTION CLOSED**\n\n{auction_results}\n**BREAK GOAL**\n${auction[3]}/${auction[2]}")
        conn.close()

@bot.tree.command(name="start-break", description="Begin a battle break.")
@app_commands.describe(
    enddatetime="Enter UNIX timestamp (e.g. 1735430520 NOT <t:1735430520:t>)",
    breakgoal="Enter the break goal amount (e.g. 150)",
    teams="Enter the teams involved seperated by comma"
)
async def startBreak(interaction: discord.Interaction, enddatetime: int, breakgoal: int, teams: str):
    teams = [team.strip() for team in teams.split(",")]
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("Not Admin.", ephemeral=True)
        return

    conn = sqlite3.connect('records.db')
    cursor = conn.cursor()

    cursor.execute('SELECT * FROM auctions WHERE channel = ? AND active = 1', (interaction.channel.id,))
    activeAuc = cursor.fetchall()

    if activeAuc:
        await interaction.response.send_message("An auction is already ongoing in this channel.", ephemeral=True)
        return
    
    cursor.execute('INSERT INTO auctions (channel, breakgoal, totalBids, enddatetime, active) VALUES (?, ?, ?, ?, ?)', 
                   (interaction.channel.id, breakgoal, 0, enddatetime, 1))
    conn.commit()

    conn = sqlite3.connect('records.db')
    cursor = conn.cursor()
    for team in teams:
        team_emoji = ':question:'  
        # Check if the team name matches any key in the emojis dictionary
        for key, value in emojis.items():
            if key.lower() in team.lower():
                team_emoji = value
                break  
        
        # Create an Item record for the team and emoji
        cursor.execute('INSERT INTO items (auctionID, itemName, emoji, endTime) VALUES (?, ?, ?, ?)', 
                       (getAuction(interaction.channel.id), team.strip(), team_emoji, enddatetime))
    
    conn.commit()
    conn.close()
    message = await getMessage(getAuction(interaction.channel.id))
    await interaction.response.send_message(message, ephemeral=True)

@bot.tree.command(name="bid", description="Bid on a team.")
@app_commands.describe(
    team = "Enter what team you would like to bid on, enter full name",
    bid = "Enter your bid amount without the $"
)
async def bid(interaction: discord.Interaction, team: str, bid: int):
    await interaction.response.defer()  # Defer the interaction to allow follow-ups

    conn = sqlite3.connect('records.db')
    cursor = conn.cursor()

    # Checks if team in auction
    cursor.execute('SELECT * FROM auctions WHERE auctionID = ?', (getAuction(interaction.channel.id),))
    auctionInfo = cursor.fetchall()

    if not auctionInfo:
        await interaction.followup.send('Auction does not exist!', ephemeral=True)
        return
    auctionInfo = auctionInfo[0]

    cursor.execute('SELECT * FROM items WHERE itemName = ? AND auctionID = ?', (team, getAuction(interaction.channel.id)))
    teamInfo = cursor.fetchall()

    if not teamInfo:
        await interaction.followup.send('Team not in break! (Type teamname caps sensitive)', ephemeral=True)
        return

    teamInfo = teamInfo[0]

    # Has time run out
    if int(datetime.now().timestamp()) > teamInfo[6]:
        await interaction.followup.send(f'This team is closed!', ephemeral=True)
        return

    # Min bids
    if teamInfo[3] < 10:
        min_bid = 1 
    elif 10 <= teamInfo[3] <= 50:
        min_bid = 2 
    else:
        min_bid = 5 

    if (bid - teamInfo[3]) < min_bid:
        await interaction.followup.send(f'Minimum bid increment is {min_bid}!', ephemeral=True)
        return

    # Logic for 5min anti-snipe
    timediff = int(datetime.now().timestamp()) - teamInfo[6]
    if timediff <= 0 and timediff >= -300:
        new_time = teamInfo[6] + 300
        cursor.execute('UPDATE items SET endTime = ? WHERE itemID = ?', (new_time, teamInfo[0]))
        conn.commit()
        if new_time > auctionInfo[4]:
            cursor.execute('UPDATE auctions SET enddatetime = ? WHERE auctionID = ?', 
                           (new_time, getAuction(interaction.channel.id)))
    conn.commit()

    # Update auction stats
    cursor.execute('UPDATE auctions SET totalBids = ? WHERE auctionID = ?', 
                   (auctionInfo[3] + bid - teamInfo[3], getAuction(interaction.channel.id)))

    # Update item stats
    cursor.execute('UPDATE items SET highestBid = ?, highestBidder = ? WHERE itemID = ?', 
                   (bid, interaction.user.id, teamInfo[0]))
    conn.commit()
    conn.close()
    
    message = await getMessage(getAuction(interaction.channel.id))
    await interaction.followup.send(message)


@bid.autocomplete("team")
async def option_autocomplete(interaction: discord.Interaction, current: str):
    try:
        await interaction.response.defer()

        conn = sqlite3.connect('records.db')
        cursor = conn.cursor()
        cursor.execute('SELECT itemName FROM items WHERE auctionID = ?', (getAuction(interaction.channel.id),))
        itemNames = cursor.fetchall()
        conn.close()

        return [
            app_commands.Choice(name=item[0], value=item[0])
            for item in itemNames if current.lower() in item[0].lower()
        ]
    except discord.errors.NotFound as e:
        print(f"Autocomplete interaction expired or invalid: {e}")


@bot.tree.command(name="cancel-break", description="Cancel the auction.")
async def endbreak(interaction: discord.Interaction):
    if interaction.user.guild_permissions.administrator:
        conn = sqlite3.connect('records.db')
        cursor = conn.cursor()
        cursor.execute('UPDATE auctions SET active = 0 WHERE auctionID = ?', (getAuction(interaction.channel.id),))
        conn.commit()
        conn.close()
        await interaction.response.send_message("Auction Cancelled")

@bot.tree.command(name="edit-time", description="Edit the ending time of the auction.")
@app_commands.describe(
    newtime = "New ending time for the auction",)
async def edittime(interaction: discord.Interaction, newtime: int):
    if interaction.user.guild_permissions.administrator:
        conn = sqlite3.connect('records.db')
        cursor = conn.cursor()

        cursor.execute('UPDATE items SET endTime = ? WHERE auctionID = ?', (newtime, getAuction(interaction.channel.id)))
        cursor.execute('UPDATE auctions SET enddatetime = ? WHERE auctionID = ?', (newtime, getAuction(interaction.channel.id)))
        conn.commit()
        conn.close()
        
        message = await getMessage(getAuction(interaction.channel.id))
        await interaction.response.send_message(message)
        await interaction.followup.send("Time Changed!", ephemeral=True)

@bot.tree.command(name="bids", description="Displays a list of the current bids.")
async def bids(interaction: discord.Interaction):
    message = await getMessage(getAuction(interaction.channel.id))
    await interaction.response.send_message(message)

@bot.tree.command(name="ping" , description="Ping the bot.")
async def ping(interaction: discord.Interaction):

    await interaction.response.send_message(f"Pong!")


def getAuction(channelID):
    conn = sqlite3.connect('records.db')
    cursor = conn.cursor()

    cursor.execute('SELECT auctionID FROM auctions WHERE channel = ? AND active = 1', (channelID,))
    auctionID = cursor.fetchone()

    if auctionID is not None:
        auctionID = auctionID[0]
    conn.close()
    return auctionID

async def getMessage(auctionID):
    conn = sqlite3.connect('records.db')
    cursor = conn.cursor()

    message = f"**CURRENT BIDS**\n\n"

    cursor.execute('SELECT * FROM items WHERE auctionID = ?', (auctionID,))
    teams = cursor.fetchall()

    for team in teams:
        # Check if the item has ended
        if team[6] < int(datetime.now().timestamp()):
            status = f"**CLOSED**"
        else:
            status = f"Closes <t:{team[6]}:R>"
        
        # If there is a bidder
        if team[4] != 0:
            # Attempt to get the display name
            user_id = team[4]
            member = bot.get_user(user_id)  # Cached user object
            if not member:  # If not cached, fetch the user
                member = await bot.fetch_user(user_id)
            bidder = member.display_name if hasattr(member, 'display_name') else member.name
            bidder = f'**@{bidder}**'
        else:
            bidder = ""

        message += f'{team[5]} {team[2]} - ${team[3]} {bidder} {status}\n'
    
    cursor.execute('SELECT totalBids, breakgoal, enddatetime FROM auctions WHERE auctionID = ?', (auctionID,))
    auctionDetails = cursor.fetchall()[0]

    conn.close()

    message += f'\n**BREAK GOAL**\n${auctionDetails[0]}/${auctionDetails[1]}\n\n⏰ Ends at <t:{auctionDetails[2]}:t>\n\n*/bid - bid on a team.\n/bids - view the current bids.*'
    return message


bot.run(token)
