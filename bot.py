import discord, json, os, requests, asyncio, psutil, platform, time, shutil, zipfile
from discord.ext import tasks, commands
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# --- Configuration Variables ---
TOKEN = os.getenv("DISCORD_TOKEN")
GPT_KEY = os.getenv("OPENROUTER_API_KEY")
MODEL = os.getenv("MODEL") or "deepseek/deepseek-chat-v3-0324"
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

# --- Global Variables ---
# Owner IDs for special commands. Initialized with a default, then updated from file.
OWNER_IDS = {"708607314155798569"}

# Discord Intents: Specifies which events the bot should receive. All intents are enabled here.
intents = discord.Intents.all()
# Initialize the bot with a command prefix and intents.
bot = commands.Bot(command_prefix="!", intents=intents)
# Initialize the command tree for slash commands.
tree = bot.tree

# Data storage for bot state (channels, memory, modes, languages, blacklists, personalities).
channel_map, memory, modes, languages = {}, {}, {}, {}
blacklist_user, blacklist_server = set(), set()
personalities = {}
dm_message = "Oniichan tidak menerima DM~" # Default DM message
global_personality = None # Stores a global personality string
use_global = False # Flag to determine if global personality should be used
setdown_message = None # Message to display when bot is in setdown mode
maintenance_mode = False # Flag for bot maintenance mode

# --- Helper Functions for Data Persistence ---
def load(path, default):
    """Loads JSON data from a file, or returns a default if the file doesn't exist."""
    return json.load(open(path)) if os.path.exists(path) else default

def save(path, data):
    """Saves data to a JSON file."""
    with open(path, "w") as f:
        json.dump(data, f)

# --- Load Initial Data ---
# Load persistent data from JSON files.
channel_map = load("channels.json", {})
languages = load("language.json", {})
modes = load("modes.json", {})
# Personalities are stored with a 'data' key for server-specific personalities,
# and 'global', 'use_global', 'setdown' for global settings.
personalities = load("personalities.json", {}).get("data", {})
global_personality = load("personalities.json", {}).get("global")
use_global = load("personalities.json", {}).get("use_global", False)
setdown_message = load("personalities.json", {}).get("setdown")
try:
    # Update OWNER_IDS from a file, if it exists.
    OWNER_IDS.update(set(load("owners.json", [])))
except:
    pass # Ignore error if owners.json doesn't exist or is malformed

def save_all():
    """Saves all persistent data back to their respective JSON files."""
    save("channels.json", channel_map)
    save("language.json", languages)
    save("modes.json", modes)
    save("owners.json", list(OWNER_IDS)) # Convert set to list for JSON serialization
    save("personalities.json", {
        "data": personalities,
        "global": global_personality,
        "use_global": use_global,
        "setdown": setdown_message
    })

# --- Memory Management Functions ---
def get_mem_key(msg):
    """Generates a unique key for user memory based on guild and user ID."""
    return f"{msg.guild.id}-{msg.author.id}"

def add_mem(msg, role, content):
    """Adds a message to the user's conversation memory, keeping only the last 10 entries."""
    k = get_mem_key(msg)
    memory.setdefault(k, []).append({"role": role, "content": content})
    memory[k] = memory[k][-10:] # Keep only the last 10 messages for context

def clear_memory():
    """Clears all stored conversation memories."""
    memory.clear()

def force_all_servers_use_global():
    """Forces all servers to use the global personality by overwriting their specific personalities."""
    for gid in personalities:
        personalities[gid] = global_personality
    save_all()

# --- GPT Interaction Function ---
def ask_gpt(messages):
    """Sends messages to the GPT model via OpenRouter API and returns the response."""
    try:
        res = requests.post("https://openrouter.ai/api/v1/chat/completions", headers={
            "Authorization": f"Bearer {GPT_KEY}",
            "Content-Type": "application/json"
        }, json={"model": MODEL, "messages": messages})
        res.raise_for_status() # Raise an HTTPError for bad responses (4xx or 5xx)
        return res.json()['choices'][0]['message']['content']
    except requests.exceptions.RequestException as e:
        return f"⚠️ Oniichan error connecting to API: {e}"
    except KeyError:
        return "⚠️ Oniichan error: Unexpected response format from API."
    except Exception as e:
        return f"⚠️ Oniichan error: {e}"

# --- Webhook Logging Function ---
def log_to_webhook(user, content, response):
    """Sends conversation logs to a configured webhook URL."""
    try:
        text = f"👤 {user}\n💬 {content}\n💖 Oniichan: {response}"
        requests.post(WEBHOOK_URL, json={"content": text})
    except:
        pass # Ignore webhook errors

# --- Discord Event Handlers ---
@bot.event
async def on_ready():
    """Event that fires when the bot successfully connects to Discord."""
    print(f"✅ Oniichan aktif sebagai {bot.user}")
    await tree.sync() # Sync slash commands with Discord
    status_loop.start() # Start the bot's status update loop

@tasks.loop(seconds=60)
async def status_loop():
    """Periodically updates the bot's Discord presence/status."""
    try:
        await bot.change_presence(activity=discord.Game(name="menjadi kawaii >///<"))
        await asyncio.sleep(60)
        await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name=f"{len(bot.guilds)} Server!"))
    except:
        pass # Ignore errors during status updates

# --- Utility Functions for Command Logic ---
def is_owner(user):
    """Checks if a user's ID is in the OWNER_IDS set."""
    return str(user.id) in OWNER_IDS

def server_mode(gid):
    """Retrieves the interaction mode for a given guild ID."""
    return modes.get(str(gid), {}).get("mode", "private")

def lang(gid):
    """Retrieves the language setting for a given guild ID."""
    return languages.get(str(gid), "id")

def get_personality(gid):
    """Determines the active personality for a given guild ID based on global settings and setdown mode."""
    if setdown_message: return setdown_message
    if use_global and global_personality: return global_personality
    return personalities.get(str(gid), "Kamu adalah Oniichan, asisten Discord kawaii berbahasa Indonesia.")

async def should_respond(msg):
    """Determines if the bot should respond to a given message based on various conditions."""
    # Do not respond to DMs, blacklisted users/servers, or if in maintenance mode (for non-owners).
    if msg.guild is None or str(msg.author.id) in blacklist_user or str(msg.guild.id) in blacklist_server:
        return False
    if maintenance_mode and not is_owner(msg.author): return False

    gid, cid = str(msg.guild.id), msg.channel.id
    mode = server_mode(gid)

    # If global lock is on and the channel is the mapped channel for the guild, do not respond.
    if modes.get("lockglobal") and cid == channel_map.get(gid): return False

    # Respond based on server mode:
    # "diem": Respond only if mentioned or "oni" is in the message.
    if mode == "diem": return bot.user.mentioned_in(msg) or "oni" in msg.content.lower()
    # "kacang": Respond only if the message is in the mapped channel.
    if mode == "kacang": return cid == channel_map.get(gid)
    # Default: Respond to all messages.
    return True

@bot.event
async def on_message(msg):
    """Event that fires when a message is sent in a channel the bot can see."""
    if msg.author.bot: return # Ignore messages from other bots
    if not await should_respond(msg): return # Check if bot should respond based on rules

    await msg.channel.typing() # Show "typing..." indicator
    gid = str(msg.guild.id)
    key = get_mem_key(msg)

    # Construct messages for GPT: system personality + memory + current user message.
    system = {"role": "system", "content": get_personality(gid)}
    messages = [system] + memory.get(key, []) + [{"role": "user", "content": msg.content}]

    reply = ask_gpt(messages) # Get response from GPT
    add_mem(msg, "user", msg.content) # Add user message to memory
    add_mem(msg, "assistant", reply) # Add bot response to memory
    log_to_webhook(msg.author.name, msg.content, reply) # Log conversation to webhook

    await msg.reply(reply[:2000]) # Reply to the message (Discord message limit is 2000 characters)
    await bot.process_commands(msg) # Process any traditional bot commands (e.g., !command)

# --- Slash Commands ---

# Admin Commands
@tree.command(name="setchannel", description="Set the default channel for bot interactions (Admin only).")
async def setchannel(i: discord.Interaction, channel: discord.TextChannel):
    """Sets the designated channel for bot interactions for the current guild."""
    if not i.user.guild_permissions.administrator:
        return await i.response.send_message("❌ Admin only", ephemeral=True)
    channel_map[str(i.guild.id)] = channel.id
    save("channels.json", channel_map)
    await i.response.send_message(f"✅ Channel set: {channel.mention}")

@tree.command(name="bahasa", description="Set bot language to Indonesian (Admin only).")
async def bahasa(i: discord.Interaction):
    """Sets the bot's language for the current guild to Indonesian."""
    if not i.user.guild_permissions.administrator:
        return await i.response.send_message("❌ Admin only", ephemeral=True)
    languages[str(i.guild.id)] = "id"
    save("language.json", languages)
    await i.response.send_message("🇮🇩 Bahasa diubah ke Indonesia")

@tree.command(name="english", description="Set bot language to English (Admin only).")
async def english(i: discord.Interaction):
    """Sets the bot's language for the current guild to English."""
    if not i.user.guild_permissions.administrator:
        return await i.response.send_message("❌ Admin only", ephemeral=True)
    languages[str(i.guild.id)] = "english"
    save("language.json", languages)
    await i.response.send_message("🇬🇧 Language changed to English")

@tree.command(name="setpersonality", description="Set the bot's personality for this server (Admin only).")
async def setpersonality(i: discord.Interaction, text: str):
    """Sets a custom personality string for the current guild."""
    if not i.user.guild_permissions.administrator:
        return await i.response.send_message("❌ Admin only", ephemeral=True)
    personalities[str(i.guild.id)] = text
    save_all()
    await i.response.send_message("🧠 Personality updated!")

@tree.command(name="personality", description="Show the active personality for this server.")
async def personality(i: discord.Interaction):
    """Displays the currently active personality for the guild."""
    gid = str(i.guild.id)
    status = "Setdown" if setdown_message else ("Global" if use_global else "Server")
    await i.response.send_message(f"🧠 Active Personality ({status}):\n{get_personality(gid)}")

@tree.command(name="forgotme", description="Clear your conversation memory with the bot.")
async def forgotme(i: discord.Interaction):
    """Clears the calling user's conversation memory with the bot."""
    memory.pop(f"{i.guild.id}-{i.user.id}", None)
    await i.response.send_message("🧽 Memory kamu sudah dihapus!")

@tree.command(name="forgotuser", description="Clear a specific user's conversation memory (Admin only).")
async def forgotuser(i: discord.Interaction, uid: str):
    """Clears the conversation memory for a specified user ID."""
    if not i.user.guild_permissions.administrator:
        return await i.response.send_message("❌ Admin only", ephemeral=True)
    memory.pop(f"{i.guild.id}-{uid}", None)
    await i.response.send_message(f"🧽 Memory user {uid} dihapus.")

@tree.command(name="lockchannel", description="Lock the current channel for bot responses (Admin only).")
async def lockchannel(i: discord.Interaction):
    """Locks the current channel, preventing bot responses outside of it."""
    if not i.user.guild_permissions.administrator:
        return await i.response.send_message("❌ Admin only", ephemeral=True)
    modes[str(i.channel.id)] = "locked"
    save("modes.json", modes)
    await i.response.send_message("🔒 Channel ini dikunci!")

@tree.command(name="unlockchannel", description="Unlock the current channel for bot responses (Admin only).")
async def unlockchannel(i: discord.Interaction):
    """Unlocks the current channel, allowing bot responses."""
    if not i.user.guild_permissions.administrator:
        return await i.response.send_message("❌ Admin only", ephemeral=True)
    modes.pop(str(i.channel.id), None)
    save("modes.json", modes)
    await i.response.send_message("🔓 Channel ini dibuka!")

# Public Commands
@tree.command(name="ping", description="Check the bot's latency.")
async def ping(i: discord.Interaction):
    """Responds with 'Pong!' and the bot's latency."""
    await i.response.send_message(f"🏓 Pong! ({round(bot.latency * 1000)}ms)")

# Owner Commands
@tree.command(name="setdown", description="Put the bot in setdown mode with a custom message (Owner only).")
async def setdown(i: discord.Interaction, text: str):
    """Puts the bot into a global 'setdown' mode, using the provided text as the personality."""
    if not is_owner(i.user):
        return await i.response.send_message("❌ Owner only", ephemeral=True)
    global setdown_message, use_global
    setdown_message = text
    use_global = True # Force global personality usage when in setdown
    clear_memory() # Clear all memories
    force_all_servers_use_global() # Ensure all servers use the setdown message
    save_all()
    await i.response.send_message("🔻 Bot masuk mode down semua server.")

@tree.command(name="setup", description="Send online notification to all mapped channels (Owner only).")
async def setup(i: discord.Interaction):
    """Sends an 'online' notification to all channels previously set via /setchannel."""
    if not is_owner(i.user):
        return await i.response.send_message("❌ Owner only", ephemeral=True)
    count = 0
    for gid, cid in channel_map.items():
        g = bot.get_guild(int(gid))
        ch = g.get_channel(cid) if g else None
        if ch:
            try:
                await ch.send("✨ Oniichan kembali online~ siap membantu >///<")
                count += 1
            except:
                continue # Skip channels where sending failed
    await i.response.send_message(f"✅ Notifikasi dikirim ke {count} channel.")

@tree.command(name="globalpersonality", description="Set the global personality for the bot (Owner only).")
async def globalpersonality(i: discord.Interaction, text: str):
    """Sets the global personality string that can be applied to all servers."""
    if not is_owner(i.user):
        return await i.response.send_message("❌ Owner only", ephemeral=True)
    global global_personality
    global_personality = text
    save_all()
    await i.response.send_message("🧠 Global personality diperbarui!")

@tree.command(name="onpersonality", description="Activate global personality for all servers (Owner only).")
async def onpersonality(i: discord.Interaction):
    """Activates the use of the global personality across all servers."""
    if not is_owner(i.user):
        return await i.response.send_message("❌ Owner only", ephemeral=True)
    global use_global
    use_global = True
    save_all()
    await i.response.send_message("🌐 Global personality aktif.")

@tree.command(name="offpersonality", description="Deactivate global personality (servers use their own) (Owner only).")
async def offpersonality(i: discord.Interaction):
    """Deactivates the use of the global personality, allowing servers to use their own."""
    if not is_owner(i.user):
        return await i.response.send_message("❌ Owner only", ephemeral=True)
    global use_global
    use_global = False
    save_all()
    await i.response.send_message("🌐 Global personality dimatikan.")

@tree.command(name="refresh", description="Restart the bot (Owner only).")
async def refresh(i: discord.Interaction):
    """Restarts the bot process."""
    if not is_owner(i.user):
        return await i.response.send_message("❌ Owner only", ephemeral=True)
    await i.response.send_message("🔁 Bot restarting...")
    # This command attempts to restart the script. Requires proper environment setup (e.g., Termux).
    os.execv("/data/data/com.termux/files/usr/bin/python", ["python", __file__])

@tree.command(name="updategithub", description="Update bot.py from a GitHub raw URL (Owner only).")
async def updategithub(i: discord.Interaction, url: str):
    """Updates the bot's source code from a raw GitHub URL and restarts."""
    if not is_owner(i.user):
        return await i.response.send_message("❌ Owner only", ephemeral=True)
    try:
        r = requests.get(url)
        r.raise_for_status() # Raise an HTTPError for bad responses (4xx or 5xx)
        with open("bot.py", "w") as f:
            f.write(r.text)
        await i.response.send_message("✅ Update berhasil dari GitHub! Bot akan restart.")
        os.execv("/data/data/com.termux/files/usr/bin/python", ["python", __file__])
    except requests.exceptions.RequestException as e:
        await i.response.send_message(f"❌ Gagal update dari GitHub: {e}")
    except Exception as e:
        await i.response.send_message(f"❌ Gagal update: {e}")

@tree.command(name="updatefile", description="Update bot.py by uploading a file (Owner only).")
async def updatefile(i: discord.Interaction, file: discord.Attachment):
    """Updates the bot's source code by saving an attached file and restarts."""
    if not is_owner(i.user):
        return await i.response.send_message("❌ Owner only", ephemeral=True)
    try:
        await file.save("bot.py")
        await i.response.send_message("✅ bot.py diperbarui dari file! Bot akan restart.")
        os.execv("/data/data/com.termux/files/usr/bin/python", ["python", __file__])
    except Exception as e:
        await i.response.send_message(f"❌ Gagal menyimpan file: {e}")

@tree.command(name="addowner", description="Add a user ID to the owner list (Main owner only).")
async def addowner(i: discord.Interaction, uid: str):
    """Adds a user ID to the list of bot owners. Only the main owner can use this."""
    if str(i.user.id) != "708607314155798569":
        return await i.response.send_message("❌ Hanya owner utama!", ephemeral=True)
    OWNER_IDS.add(uid)
    save("owners.json", list(OWNER_IDS))
    await i.response.send_message(f"✅ Owner `{uid}` ditambahkan.")

@tree.command(name="removeowner", description="Remove a user ID from the owner list (Main owner only).")
async def removeowner(i: discord.Interaction, uid: str):
    """Removes a user ID from the list of bot owners. Cannot remove the main owner."""
    if str(i.user.id) != "708607314155798569":
        return await i.response.send_message("❌ Hanya owner utama!", ephemeral=True)
    if uid == "708607314155798569":
        return await i.response.send_message("❌ Tidak bisa hapus owner utama!")
    OWNER_IDS.discard(uid) # Use discard to avoid error if UID not present
    save("owners.json", list(OWNER_IDS))
    await i.response.send_message(f"✅ Owner `{uid}` dihapus.")

@tree.command(name="owner", description="Show the list of bot owners (Owner only).")
async def owner(i: discord.Interaction):
    """Displays an embed listing all current bot owners."""
    if not is_owner(i.user):
        return await i.response.send_message("❌ Owner only", ephemeral=True)
    e = discord.Embed(title="👑 Owner List", color=0xff77ff)
    for uid in OWNER_IDS:
        e.add_field(name="ID", value=uid, inline=False)
    await i.response.send_message(embed=e)

@tree.command(name="maintenance", description="Turn maintenance mode ON or OFF (Owner only).")
async def maintenance(i: discord.Interaction, mode: str):
    """Toggles the bot's maintenance mode (on/off)."""
    if not is_owner(i.user):
        return await i.response.send_message("❌ Owner only", ephemeral=True)
    global maintenance_mode
    maintenance_mode = (mode.lower() == "on")
    msg = "🚧 Maintenance aktif!" if maintenance_mode else "✅ Maintenance dimatikan!"
    await i.response.send_message(msg)

@tree.command(name="send", description="Set the default DM message template (Owner only).")
async def send(i: discord.Interaction, text: str):
    """Sets the default message sent when the bot receives a DM."""
    if not is_owner(i.user):
        return await i.response.send_message("❌ Owner only", ephemeral=True)
    global dm_message
    dm_message = text
    await i.response.send_message("✉️ Template DM diubah!")

@tree.command(name="count", description="Show bot statistics (Owner only).")
async def count(i: discord.Interaction):
    """Displays statistics about the bot's servers, channels, and memory usage."""
    if not is_owner(i.user):
        return await i.response.send_message("❌ Owner only", ephemeral=True)
    e = discord.Embed(title="📊 Statistik", color=0x00ffff)
    e.add_field(name="Server", value=len(bot.guilds))
    e.add_field(name="Channel", value=sum(len(g.text_channels) for g in bot.guilds))
    e.add_field(name="Memory User", value=len(memory))
    await i.response.send_message(embed=e)

@tree.command(name="usage", description="Show bot resource usage (RAM, CPU, Ping) (Owner only).")
async def usage(i: discord.Interaction):
    """Displays the bot's current RAM, CPU usage, and Discord API ping."""
    if not is_owner(i.user):
        return await i.response.send_message("❌ Owner only", ephemeral=True)
    ram = psutil.virtual_memory().percent
    cpu = psutil.cpu_percent()
    ping = round(bot.latency * 1000)
    e = discord.Embed(title="🖥️ Usage", color=0x66ffcc)
    e.add_field(name="RAM", value=f"{ram}%")
    e.add_field(name="CPU", value=f"{cpu}%")
    e.add_field(name="Ping", value=f"{ping}ms")
    await i.response.send_message(embed=e)

@tree.command(name="blacklistuser", description="Add a user ID to the blacklist (Owner only).")
async def blacklistuser(i: discord.Interaction, uid: str):
    """Adds a user ID to the bot's blacklist, preventing it from responding to them."""
    if not is_owner(i.user):
        return await i.response.send_message("❌ Owner only", ephemeral=True)
    blacklist_user.add(uid)
    await i.response.send_message(f"🚫 User `{uid}` diblacklist!")

@tree.command(name="blacklistserver", description="Add a server ID to the blacklist (Owner only).")
async def blacklistserver(i: discord.Interaction, sid: str):
    """Adds a server ID to the bot's blacklist, preventing it from responding in that server."""
    if not is_owner(i.user):
        return await i.response.send_message("❌ Owner only", ephemeral=True)
    blacklist_server.add(sid)
    await i.response.send_message(f"🚫 Server `{sid}` diblacklist!")

@tree.command(name="clearmemory", description="Clear all user conversation memories (Owner only).")
async def clearmemory(i: discord.Interaction):
    """Clears all conversation memories stored by the bot."""
    if not is_owner(i.user):
        return await i.response.send_message("❌ Owner only", ephemeral=True)
    clear_memory()
    await i.response.send_message("🧽 Semua memory user dihapus!")

@tree.command(name="lockglobal", description="Globally lock all bot channels (Owner only).")
async def lockglobal(i: discord.Interaction):
    """Activates a global lock, preventing bot responses in all mapped channels."""
    if not is_owner(i.user):
        return await i.response.send_message("❌ Owner only", ephemeral=True)
    modes["lockglobal"] = True
    save("modes.json", modes)
    await i.response.send_message("🔒 Semua channel bot dikunci global!")

@tree.command(name="unlockglobal", description="Globally unlock all bot channels (Owner only).")
async def unlockglobal(i: discord.Interaction):
    """Deactivates the global lock, allowing bot responses in mapped channels again."""
    if not is_owner(i.user):
        return await i.response.send_message("❌ Owner only", ephemeral=True)
    modes.pop("lockglobal", None)
    save("modes.json", modes)
    await i.response.send_message("🔓 Semua channel bot dibuka kembali!")

@tree.command(name="clearglobal", description="Delete all bot messages from channels (Owner only).")
async def clearglobal(i: discord.Interaction, target: str):
    """Deletes all messages sent by the bot, either from all servers or a specific server."""
    if not is_owner(i.user):
        return await i.response.send_message("❌ Owner only", ephemeral=True)
    count = 0
    if target == "all":
        # Iterate through all guilds and their text channels
        for g in bot.guilds:
            for ch in g.text_channels:
                try:
                    # Fetch message history and delete messages sent by the bot
                    async for m in ch.history():
                        if m.author == bot.user:
                            await m.delete()
                            count += 1
                except discord.Forbidden:
                    # Bot doesn't have permissions to read history or delete messages
                    print(f"Missing permissions in channel {ch.name} ({ch.id}) in guild {g.name} ({g.id})")
                    continue
                except Exception as e:
                    print(f"Error clearing messages in channel {ch.name}: {e}")
                    continue
    else:
        # Clear messages from a specific guild
        g = bot.get_guild(int(target))
        if g:
            for ch in g.text_channels:
                try:
                    async for m in ch.history():
                        if m.author == bot.user:
                            await m.delete()
                            count += 1
                except discord.Forbidden:
                    print(f"Missing permissions in channel {ch.name} ({ch.id}) in guild {g.name} ({g.id})")
                    continue
                except Exception as e:
                    print(f"Error clearing messages in channel {ch.name}: {e}")
                    continue
        else:
            await i.response.send_message(f"❌ Server dengan ID `{target}` tidak ditemukan.")
            return

    await i.response.send_message(f"🗑️ {count} pesan bot dihapus.")

@tree.command(name="backup", description="Create a zip backup of bot data files (Owner only).")
async def backup(i: discord.Interaction):
    """Creates a zip archive of essential bot data files and sends it to the owner."""
    if not is_owner(i.user):
        return await i.response.send_message("❌ Owner only", ephemeral=True)
    zipname = f"backup_{int(time.time())}.zip"
    try:
        with zipfile.ZipFile(zipname, 'w') as zipf:
            # List of files to include in the backup
            files_to_backup = [
                "channels.json",
                "owners.json",
                "language.json",
                "modes.json",
                "personalities.json"
            ]
            for file in files_to_backup:
                if os.path.exists(file):
                    zipf.write(file)
                else:
                    print(f"Warning: File not found for backup: {file}")
        await i.response.send_message(file=discord.File(zipname))
    except Exception as e:
        await i.response.send_message(f"❌ Gagal membuat backup: {e}")
    finally:
        # Clean up the created zip file
        if os.path.exists(zipname):
            os.remove(zipname)


# --- Run the Bot ---
# This must be the last line in the script to start the bot.
bot.run(TOKEN)

