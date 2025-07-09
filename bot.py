import discord, json, os, requests, asyncio, psutil
from discord.ext import tasks

TOKEN = "MTM5MjM2MjkxNjkwNDE3MzYxOQ.G5Tr1e.Ro4_SvBU6x9nharNVIEJscxpKYgg1V_6jMelYk"
OPENROUTER_API_KEY = "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"
MODEL = "deepseek/deepseek-chat-v3-0324"
WEBHOOK_URL = "https://discord.com/api/webhooks/1392409095146832043/gmAiAETsvTSnWo5MfBY9Os_eWy1tEjQHb5WP3HrN7fF7VkDPHEKaEk55PiMXcTDKG6ns"
OWNER_IDS = {"708607314155798569"}

intents = discord.Intents.all()
bot = discord.Client(intents=intents)
tree = discord.app_commands.CommandTree(bot)

channel_map, memory, modes, languages = {}, {}, {}, {}
owner_file, personality_file, language_file = "owners.json", "personalities.json", "language.json"
dm_message, global_personality = "Oniichan tidak menerima DM~", None
use_global, maintenance_mode = False, False

if os.path.exists(owner_file): OWNER_IDS.update(set(json.load(open(owner_file))))
if os.path.exists("channels.json"): channel_map = json.load(open("channels.json"))
if os.path.exists(personality_file): 
  raw = json.load(open(personality_file)); personalities = raw.get("data", {}); 
  global_personality, use_global = raw.get("global"), raw.get("use_global", False)
else: personalities = {}
if os.path.exists(language_file): languages = json.load(open(language_file))

def save_all(): 
  json.dump({"data": personalities, "global": global_personality, "use_global": use_global}, open(personality_file,"w"))
  json.dump(languages, open(language_file,"w"))

def get_mem_key(msg): return f"{msg.guild.id}-{msg.author.id}"
def add_mem(msg, role, content): k=get_mem_key(msg); memory.setdefault(k,[]).append({"role": role, "content": content}); memory[k]=memory[k][-10:]
def clear_memory(): memory.clear()
def force_global(): 
  for gid in personalities: personalities[gid] = global_personality
  save_all()

def ask(messages):
  try: r = requests.post("https://openrouter.ai/api/v1/chat/completions", headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"}, json={"model": MODEL,"messages":messages})
  except Exception as e: return f"⚠️ Error: {e}"
  return r.json()['choices'][0]['message']['content']

def log(user, content, reply): 
  try: requests.post(WEBHOOK_URL, json={"content": f"👤 {user}\n💬 {content}\n💖 Oniichan: {reply}"})
  except: pass

@bot.event
async def on_ready():
  print(f"Oniichan aktif sebagai {bot.user}")
  try: await tree.sync()
  except: pass
  for g in channel_map: modes[g] = modes.get(g, "private")
  switch_status.start()

@tasks.loop(seconds=60)
async def switch_status():
  await bot.change_presence(activity=discord.Game(name="menjadi kawaii >///<"))
  await asyncio.sleep(60)
  await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name=f"{len(bot.guilds)} Server!"))

# ========== SLASH ==========
@tree.command(name="setchannel")
async def setchannel(i:discord.Interaction, channel:discord.TextChannel):
  if not i.user.guild_permissions.administrator: return await i.response.send_message("❌ Hanya admin.", ephemeral=True)
  channel_map[str(i.guild.id)] = channel.id; json.dump(channel_map, open("channels.json","w")); modes[str(i.guild.id)] = "private"
  await i.response.send_message(f"✅ Channel {channel.mention} diset!")

@tree.command(name="setpersonality")
async def setpersonality(i:discord.Interaction, text:str):
  if not i.user.guild_permissions.administrator: return await i.response.send_message("❌ Hanya admin.", ephemeral=True)
  personalities[str(i.guild.id)] = text; save_all(); await i.response.send_message("✅ Personality server diatur!")

@tree.command(name="personality")
async def personality(i:discord.Interaction):
  gid = str(i.guild.id)
  p = personalities.get(gid, "(default kawaii)")
  await i.response.send_message(f"🎭 Personality: {p}")

@tree.command(name="globalpersonality")
async def globalp(i:discord.Interaction, text:str):
  if str(i.user.id) not in OWNER_IDS: return await i.response.send_message("❌ Owner only", ephemeral=True)
  global global_personality; global_personality = text; save_all(); await i.response.send_message("✅ Global personality diatur!")

@tree.command(name="onpersonality")
async def onp(i:discord.Interaction):
  if str(i.user.id) not in OWNER_IDS: return await i.response.send_message("❌ Owner only", ephemeral=True)
  global use_global; use_global = True; save_all(); await i.response.send_message("🌐 Global personality aktif")

@tree.command(name="offpersonality")
async def offp(i:discord.Interaction):
  if str(i.user.id) not in OWNER_IDS: return await i.response.send_message("❌ Owner only", ephemeral=True)
  global use_global; use_global = False; save_all(); await i.response.send_message("🌐 Global personality dimatikan")

@tree.command(name="setdown")
async def setdown(i:discord.Interaction, text:str):
  if str(i.user.id) not in OWNER_IDS: return await i.response.send_message("❌ Owner only", ephemeral=True)
  global global_personality, use_global; global_personality = text; use_global = True
  clear_memory(); force_global(); await i.response.send_message("🔻 Setdown aktif")

@tree.command(name="setup")
async def setup(i:discord.Interaction):
  if str(i.user.id) not in OWNER_IDS: return await i.response.send_message("❌ Owner only", ephemeral=True)
  c=0
  for g in bot.guilds:
    cid=channel_map.get(str(g.id)); ch=g.get_channel(cid) if cid else None
    if ch: await ch.send("✨ Oniichan kembali online!"); c+=1
  await i.response.send_message(f"✅ Notifikasi ke {c} channel")

@tree.command(name="refresh")
async def refresh(i:discord.Interaction):
  if str(i.user.id) not in OWNER_IDS: return await i.response.send_message("❌ Owner only", ephemeral=True)
  await i.response.send_message("🔄 Restarting..."); os.execv("/data/data/com.termux/files/usr/bin/python", ["python", __file__])

@tree.command(name="owner")
async def owner(i:discord.Interaction):
  if str(i.user.id) not in OWNER_IDS: return await i.response.send_message("❌", ephemeral=True)
  e=discord.Embed(title="👑 Owner List", color=0xff66cc)
  for o in OWNER_IDS: e.add_field(name="ID", value=o)
  await i.response.send_message(embed=e)

@tree.command(name="count")
async def count(i:discord.Interaction):
  if str(i.user.id) not in OWNER_IDS: return await i.response.send_message("❌", ephemeral=True)
  e = discord.Embed(title="📊 Statistik", color=0x00ffcc)
  e.add_field(name="Server", value=str(len(bot.guilds)))
  e.add_field(name="Channel", value=str(len(channel_map)))
  e.add_field(name="User", value=str(len(memory)))
  await i.response.send_message(embed=e)

@tree.command(name="ping")
async def ping(i:discord.Interaction): await i.response.send_message(f"Pong! `{round(bot.latency*1000)}ms`")

@tree.command(name="usage")
async def usage(i:discord.Interaction):
  if str(i.user.id) not in OWNER_IDS: return await i.response.send_message("❌", ephemeral=True)
  import platform, psutil
  ram = psutil.virtual_memory().percent
  cpu = psutil.cpu_percent()
  e = discord.Embed(title="📟 Usage", color=0xaa66ff)
  e.add_field(name="Ping", value=f"{round(bot.latency*1000)}ms")
  e.add_field(name="RAM", value=f"{ram}%")
  e.add_field(name="CPU", value=f"{cpu}%")
  await i.response.send_message(embed=e)

@tree.command(name="maintenance")
async def maintenance(i:discord.Interaction, mode:str):
  if str(i.user.id) not in OWNER_IDS: return await i.response.send_message("❌", ephemeral=True)
  global maintenance_mode
  maintenance_mode = (mode=="on")
  await i.response.send_message("✅ Maintenance aktif" if maintenance_mode else "✅ Maintenance mati")

@tree.command(name="kacang")
async def kacang(i:discord.Interaction):
  gid = str(i.guild.id)
  modes[gid] = "normal" if modes.get(gid)=="kacang" else "kacang"
  await i.response.send_message("🥜 Mode kacang toggle!")

@tree.command(name="diem")
async def diem(i:discord.Interaction):
  gid = str(i.guild.id)
  modes[gid] = "normal" if modes.get(gid)=="diem" else "diem"
  await i.response.send_message("😶 Mode diem toggle!")

@tree.command(name="private")
async def private(i:discord.Interaction):
  gid = str(i.guild.id)
  modes[gid] = "normal" if modes.get(gid)=="private" else "private"
  await i.response.send_message("🔐 Mode private toggle!")

@tree.command(name="forgotme")
async def forgotme(i:discord.Interaction):
  memory.pop(get_mem_key(i), None)
  await i.response.send_message("✅ Memori kamu dihapus.")

@tree.command(name="forgotuser")
async def forgotuser(i:discord.Interaction, user_id:str):
  if str(i.user.id) not in OWNER_IDS: return await i.response.send_message("❌", ephemeral=True)
  for k in list(memory): 
    if user_id in k: memory.pop(k)
  await i.response.send_message("✅ Dihapus.")

@tree.command(name="bahasa")
async def bahasa(i:discord.Interaction):
  languages[str(i.guild.id)] = "id"; save_all()
  await i.response.send_message("✅ Bahasa diatur: Indonesia")

@tree.command(name="english")
async def english(i:discord.Interaction):
  languages[str(i.guild.id)] = "en"; save_all()
  await i.response.send_message("✅ Language set to English")

# ===== RESPON LOGIK =====

async def should_respond(msg):
  if maintenance_mode and str(msg.author.id) not in OWNER_IDS: return False
  gid = str(msg.guild.id)
  mode = modes.get(gid, "private")
  cid = channel_map.get(gid)
  if mode=="diem": return bot.user.mentioned_in(msg) or "oni" in msg.content.lower()
  if mode in ["kacang", "private"]: return msg.channel.id == cid
  return True

@bot.event
async def on_message(msg):
  if msg.author.bot: return
  if msg.guild is None: return await msg.author.send(dm_message)
  if not await should_respond(msg): return
  await msg.channel.typing()
  k = get_mem_key(msg)
  lang = languages.get(str(msg.guild.id), "id")
  if global_personality:
    system = {"role":"system","content":global_personality if lang=="id" else "Oniichan is down... Please wait."}
  elif str(msg.guild.id) in personalities:
    system = {"role":"system","content":personalities[str(msg.guild.id)]}
  else:
    system = {"role":"system","content":"Kamu adalah Oniichan, asisten kawaii Discord >///<"}

  chat = [system] + memory.get(k, []) + [{"role":"user","content":msg.content}]
  reply = ask(chat)
  add_mem(msg,"user",msg.content); add_mem(msg,"assistant",reply)
  log(msg.author.name, msg.content, reply)
  await msg.reply(reply[:2000])

bot.run(TOKEN)# bot
