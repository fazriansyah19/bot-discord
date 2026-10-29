import os
import discord
from discord.ext import commands
from discord import app_commands
import sqlite3

# ====== KONFIGURASI ======import os
TOKEN = os.environ.get("DISCORD_TOKEN")
GUILD_ID = 1559949579066146900

# ====== DATABASE SETUP ======
conn = sqlite3.connect('klan.db')
cursor = conn.cursor()
cursor.execute('''
    CREATE TABLE IF NOT EXISTS anggota (
        discord_id INTEGER PRIMARY KEY,
        nama_ingame TEXT NOT NULL,
        job TEXT,
        tanggal_daftar TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
''')
conn.commit()

# ====== BOT SETUP ======
intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ====== FUNGSI HELPER (BUKAN COMMAND) ======
def buat_nickname(nama: str, job: str, maks: int = 32) -> str:
    suffix = f" | {job}"
    if len(nama) + len(suffix) <= maks:
        return nama + suffix
    return nama[:maks]

# ====== EVENT ON_READY ======
@bot.event
async def on_ready():
    try:
        synced = await bot.tree.sync(guild=discord.Object(id=GUILD_ID))
        print(f"✅ Bot siap! {len(synced)} slash command tersinkron.")
    except Exception as e:
        print(f"❌ Gagal sync: {e}")
    print(f"Login sebagai {bot.user}")

# ====== COMMAND /daftar ======
@bot.tree.command(name="daftar", description="Daftarkan nama in-game kamu", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(nama="Nama in-game kamu", job="Job kamu (contoh: Ahli Bangunan)")
async def daftar(interaction: discord.Interaction, nama: str, job: str):
    cursor.execute('''
        INSERT OR REPLACE INTO anggota (discord_id, nama_ingame, job)
        VALUES (?, ?, ?)
    ''', (interaction.user.id, nama, job))
    conn.commit()

    me = interaction.guild.me
    target = interaction.user
    nick_baru = buat_nickname(nama, job)

    if target == interaction.guild.owner:
        nick_status = "❌ Tidak dapat mengubah nickname Pemilik Server."
    elif me.top_role <= target.top_role:
        nick_status = f"❌ Role bot ({me.top_role.name}) lebih rendah dari role anggota ({target.top_role.name})."
    else:
        try:
            await target.edit(nick=nick_baru)
            nick_status = f"✅ Nickname diubah menjadi: `{nick_baru}`"
        except discord.Forbidden:
            nick_status = "❌ Izin ditolak, periksa izin Manage Nicknames."
        except discord.HTTPException as e:
            nick_status = f"❌ Gagal ubah nickname: {e}"

    await interaction.response.send_message(
        f"✅ Terdaftar!\n**Nama in-game:** {nama}\n**Job:** {job}\n{nick_status}",
        ephemeral=True
    )

# ====== COMMAND /ceknama ======
@bot.tree.command(name="ceknama", description="Cek nama in-game seseorang", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(user="Pilih member yang mau dicek")
async def ceknama(interaction: discord.Interaction, user: discord.Member):
    cursor.execute('SELECT nama_ingame, job FROM anggota WHERE discord_id = ?', (user.id,))
    hasil = cursor.fetchone()

    if hasil:
        nama, job = hasil
        await interaction.response.send_message(
            f"🎮 **{user.display_name}**\nNama in-game: **{nama}**\nJob: **{job}**"
        )
    else:
        await interaction.response.send_message(
            f"❌ {user.display_name} belum mendaftar.", ephemeral=True
        )

# ====== COMMAND /daftaranggota ======
@bot.tree.command(name="daftaranggota", description="Lihat semua anggota terdaftar", guild=discord.Object(id=GUILD_ID))
async def daftaranggota(interaction: discord.Interaction):
    cursor.execute('SELECT nama_ingame, job FROM anggota ORDER BY job, nama_ingame')
    semua = cursor.fetchall()

    if not semua:
        await interaction.response.send_message("Belum ada anggota yang mendaftar.")
        return

    per_job = {}
    for nama, job in semua:
        per_job.setdefault(job, []).append(nama)

    embed = discord.Embed(title="📋 Daftar Anggota Klan", color=discord.Color.gold())
    for job, nama_list in per_job.items():
        embed.add_field(
            name=f"⚒️ {job}",
            value="\n".join(f"• {n}" for n in nama_list),
            inline=False
        )

    await interaction.response.send_message(embed=embed)

# ====== JALANKAN BOT ======
bot.run(TOKEN)