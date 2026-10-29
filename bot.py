import os
import discord
from discord.ext import commands
from discord import app_commands
import sqlite3
from datetime import datetime

# ====== KONFIGURASI ======
TOKEN = os.environ.get("DISCORD_TOKEN")
GUILD_ID = 1559949579066146900

# ====== DAFTAR JOB (untuk select menu) ======
DAFTAR_JOB = [
    "Ahli Bangunan",
    "Boss Penjahit",
    "Pakar Alat & Senjata",
    "Penyetok Barang",
    "Petani",
    "Supervisor MBG",
]

# ====== DATABASE SETUP ======
conn = sqlite3.connect('klan.db')
cursor = conn.cursor()

# Tabel utama anggota (tanpa kolom job)
cursor.execute('''
    CREATE TABLE IF NOT EXISTS anggota (
        discord_id INTEGER PRIMARY KEY,
        nama_ingame TEXT NOT NULL,
        tanggal_daftar TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
''')

# Tabel relasi anggota <-> job (many-to-many)
cursor.execute('''
    CREATE TABLE IF NOT EXISTS anggota_job (
        discord_id INTEGER,
        job TEXT,
        PRIMARY KEY (discord_id, job),
        FOREIGN KEY (discord_id) REFERENCES anggota(discord_id) ON DELETE CASCADE
    )
''')
conn.commit()

# Tabel aliansi klan
cursor.execute('''
    CREATE TABLE IF NOT EXISTS aliansi (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nama_klan TEXT NOT NULL UNIQUE,
        deskripsi TEXT,
        status TEXT DEFAULT 'Aktif',
        tanggal TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
''')
conn.commit()

# Migrasi otomatis: kalau tabel lama masih punya kolom job, pindahkan ke anggota_job
try:
    cursor.execute("PRAGMA table_info(anggota)")
    kolom = [row[1] for row in cursor.fetchall()]
    if "job" in kolom:
        cursor.execute("SELECT discord_id, job FROM anggota WHERE job IS NOT NULL AND job != ''")
        for did, job_lama in cursor.fetchall():
            for j in [x.strip() for x in job_lama.split(",") if x.strip()]:
                cursor.execute(
                    "INSERT OR IGNORE INTO anggota_job (discord_id, job) VALUES (?, ?)",
                    (did, j)
                )
        conn.commit()
        print("✅ Migrasi data job lama selesai.")
except Exception as e:
    print(f"⚠️ Migrasi dilewati: {e}")

# ====== BOT SETUP ======
intents = discord.Intents.default()
intents.members = True
intents.reactions = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ====== FUNGSI HELPER ======
def buat_nickname(nama: str, maks: int = 32) -> str:
    """Nickname hanya berisi nama in-game, dipotong jika > 32 karakter."""
    return nama[:maks]

def ambil_job(discord_id: int) -> list:
    cursor.execute("SELECT job FROM anggota_job WHERE discord_id = ? ORDER BY job", (discord_id,))
    return [row[0] for row in cursor.fetchall()]

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
@app_commands.describe(nama="Nama in-game kamu (nickname Discord akan diubah ke nama ini)")
async def daftar(interaction: discord.Interaction, nama: str):
    user = interaction.user

    # Cek apakah sudah pilih job di #pilih-job
    job_di_server = {r.name for r in user.roles if r.name in DAFTAR_JOB}

    # Simpan / update nama
    cursor.execute(
        "INSERT OR REPLACE INTO anggota (discord_id, nama_ingame) VALUES (?, ?)",
        (user.id, nama)
    )
    # Sinkronkan job dari role Discord ke database
    cursor.execute("DELETE FROM anggota_job WHERE discord_id = ?", (user.id,))
    for j in job_di_server:
        cursor.execute(
            "INSERT OR IGNORE INTO anggota_job (discord_id, job) VALUES (?, ?)",
            (user.id, j)
        )
    conn.commit()

    # Ubah nickname (hanya nama, tanpa job)
    me = interaction.guild.me
    target = user
    nick_baru = buat_nickname(nama)

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

    # Pesan balasan
    job_str = ", ".join(sorted(job_di_server)) if job_di_server else "Belum dipilih"
    peringatan = ""
    if not job_di_server:
        peringatan = (
            "\n\n⚠️ Kamu belum memilih job. "
            "Buka `#pilih-job` dan pilih job lewat dropdown."
        )

    await interaction.response.send_message(
        f"✅ Terdaftar!\n"
        f"**Nama in-game:** {nama}\n"
        f"**Job:** {job_str}\n"
        f"{nick_status}"
        f"{peringatan}",
        ephemeral=True
    )

# ====== COMMAND /ceknama ======
@bot.tree.command(name="ceknama", description="Cek nama in-game seseorang", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(user="Pilih member yang mau dicek")
async def ceknama(interaction: discord.Interaction, user: discord.Member):
    cursor.execute("SELECT nama_ingame FROM anggota WHERE discord_id = ?", (user.id,))
    hasil = cursor.fetchone()

    if hasil:
        nama = hasil[0]
        jobs = ambil_job(user.id)
        job_str = ", ".join(jobs) if jobs else "Belum diisi"
        await interaction.response.send_message(
            f"🎮 **{user.display_name}**\nNama in-game: **{nama}**\nJob: **{job_str}**"
        )
    else:
        await interaction.response.send_message(
            f"❌ {user.display_name} belum mendaftar.", ephemeral=True
        )


# ====== COMMAND /daftaranggota ======
@bot.tree.command(name="daftaranggota", description="Lihat semua anggota terdaftar", guild=discord.Object(id=GUILD_ID))
async def daftaranggota(interaction: discord.Interaction):
    cursor.execute("SELECT discord_id, nama_ingame FROM anggota ORDER BY nama_ingame")
    semua = cursor.fetchall()

    if not semua:
        await interaction.response.send_message("Belum ada anggota yang mendaftar.")
        return

    # Kelompokkan berdasarkan job (satu anggota bisa muncul di beberapa job)
    per_job = {}
    tanpa_job = []
    for did, nama in semua:
        jobs = ambil_job(did)
        if not jobs:
            tanpa_job.append(nama)
        for j in jobs:
            per_job.setdefault(j, []).append(nama)

    embed = discord.Embed(title="📋 Daftar Anggota Klan", color=discord.Color.gold())
    for job, nama_list in sorted(per_job.items()):
        embed.add_field(
            name=f"⚒️ {job}",
            value="\n".join(f"• {n}" for n in nama_list),
            inline=False
        )
    if tanpa_job:
        embed.add_field(
            name="❓ Belum Ada Job",
            value="\n".join(f"• {n}" for n in tanpa_job),
            inline=False
        )

    await interaction.response.send_message(embed=embed)


# ====== FITUR 2: /profil ======
@bot.tree.command(name="profil", description="Lihat kartu profil anggota klan", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(user="Pilih member (kosongkan untuk profil sendiri)")
async def profil(interaction: discord.Interaction, user: discord.Member = None):
    target = user or interaction.user
    cursor.execute(
        "SELECT nama_ingame, tanggal_daftar FROM anggota WHERE discord_id = ?",
        (target.id,)
    )
    hasil = cursor.fetchone()

    if not hasil:
        await interaction.response.send_message(
            f"❌ {target.display_name} belum mendaftar. Ketik `/daftar` dulu.",
            ephemeral=True
        )
        return

    nama, tgl = hasil
    jobs = ambil_job(target.id)
    job_str = ", ".join(jobs) if jobs else "Belum diisi"

    try:
        tgl_dt = datetime.fromisoformat(tgl)
        lama = (datetime.now() - tgl_dt).days
        lama_str = f"{lama} hari"
    except Exception:
        lama_str = "tidak diketahui"

    embed = discord.Embed(
        title=f"🎮 Profil {target.display_name}",
        color=discord.Color.gold()
    )
    embed.set_thumbnail(url=target.display_avatar.url)
    embed.add_field(name="Nama In-Game", value=nama, inline=True)
    embed.add_field(name="Bergabung", value=lama_str, inline=True)
    embed.add_field(name="Job", value=job_str, inline=False)
    embed.set_footer(text=f"Discord ID: {target.id}")

    await interaction.response.send_message(embed=embed)


# ====== FITUR 3: /statistik ======
@bot.tree.command(name="statistik", description="Lihat statistik keanggotaan klan", guild=discord.Object(id=GUILD_ID))
async def statistik(interaction: discord.Interaction):
    cursor.execute("SELECT job, COUNT(*) FROM anggota_job GROUP BY job ORDER BY COUNT(*) DESC")
    per_job = cursor.fetchall()

    cursor.execute("SELECT COUNT(*) FROM anggota")
    total_terdaftar = cursor.fetchone()[0]

    # Hitung member yang belum daftar (hanya manusia, bukan bot)
    semua_member = [m for m in interaction.guild.members if not m.bot]
    terdaftar_ids = set()
    cursor.execute("SELECT discord_id FROM anggota")
    for row in cursor.fetchall():
        terdaftar_ids.add(row[0])
    belum_daftar = len([m for m in semua_member if m.id not in terdaftar_ids])

    embed = discord.Embed(title="📊 Statistik Klan", color=discord.Color.blurple())
    embed.add_field(name="Total Terdaftar", value=str(total_terdaftar), inline=True)
    embed.add_field(name="Belum Daftar", value=str(belum_daftar), inline=True)
    embed.add_field(name="\u200b", value="\u200b", inline=True)

    if per_job:
        job_lines = "\n".join(f"• **{job}**: {jml} orang" for job, jml in per_job)
        embed.add_field(name="Distribusi Job", value=job_lines, inline=False)
    else:
        embed.add_field(name="Distribusi Job", value="Belum ada data job.", inline=False)

    await interaction.response.send_message(embed=embed)


# ====== FITUR 4: /carijob ======
@bot.tree.command(name="carijob", description="Cari anggota berdasarkan job", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(job="Nama job yang dicari (contoh: Ahli Bangunan)")
async def carijob(interaction: discord.Interaction, job: str):
    cursor.execute(
        """SELECT a.nama_ingame, a.discord_id
           FROM anggota a
           JOIN anggota_job aj ON a.discord_id = aj.discord_id
           WHERE LOWER(aj.job) LIKE ?
           ORDER BY a.nama_ingame""",
        (f"%{job.lower()}%",)
    )
    hasil = cursor.fetchall()

    if not hasil:
        await interaction.response.send_message(
            f"❌ Tidak ada anggota dengan job mengandung '{job}'.", ephemeral=True
        )
        return

    lines = []
    for nama, did in hasil:
        member = interaction.guild.get_member(did)
        mention = member.mention if member else "*(keluar server)*"
        lines.append(f"• **{nama}** — {mention}")

    embed = discord.Embed(
        title=f"⚒️ Anggota dengan job '{job}'",
        description="\n".join(lines),
        color=discord.Color.green()
    )
    embed.set_footer(text=f"Total: {len(hasil)} orang")
    await interaction.response.send_message(embed=embed)


# ====== CEK IZIN ADMIN KLAN ======
def is_admin_klan(member: discord.Member) -> bool:
    if member.guild is None:
        return False
    owner = member.guild.owner
    if owner is not None and member.id == owner.id:
        return True
    nama_role = " ".join(r.name.lower() for r in member.roles)
    kata_kunci = ["ketua", "tetua", "wakil", "leader", "admin", "budak member", "wakil rakyat"]
    return any(k in nama_role for k in kata_kunci)

# ====== COMMAND /export ======
@bot.tree.command(name="export", description="Backup database klan (khusus Ketua/Tetua)", guild=discord.Object(id=GUILD_ID))
async def export_db(interaction: discord.Interaction):
    if not is_admin_klan(interaction.user):
        await interaction.response.send_message(
            "❌ Hanya Ketua/Tetua yang boleh backup database.", ephemeral=True
        )
        return

    # Pastikan semua perubahan sudah ditulis ke file
    conn.commit()

    if not os.path.exists("klan.db"):
        await interaction.response.send_message(
            "❌ File database tidak ditemukan.", ephemeral=True
        )
        return

    # Kirim file sebagai attachment, ephemeral supaya tidak bocor ke channel
    file = discord.File("klan.db", filename=f"klan_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db")
    await interaction.response.send_message(
        f"✅ Backup database berhasil dibuat.\n"
        f"**Waktu:** {datetime.now().strftime('%d %B %Y, %H:%M')}\n"
        f"Simpan file ini di tempat aman.",
        file=file,
        ephemeral=True
    )


# ====== COMMAND /import ======
@bot.tree.command(name="import", description="Restore database klan dari file backup (khusus Ketua/Tetua)", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(file="File .db hasil /export sebelumnya")
async def import_db(interaction: discord.Interaction, file: discord.Attachment):
    if not is_admin_klan(interaction.user):
        await interaction.response.send_message(
            "❌ Hanya Ketua/Tetua yang boleh restore database.", ephemeral=True
        )
        return

    # Validasi ekstensi
    if not file.filename.lower().endswith(".db"):
        await interaction.response.send_message(
            "❌ File harus berekstensi `.db` (hasil dari /export).", ephemeral=True
        )
        return

    # Validasi ukuran (SQLite biasanya kecil, batasi 8 MB)
    if file.size > 8 * 1024 * 1024:
        await interaction.response.send_message(
            "❌ File terlalu besar (maks 8 MB).", ephemeral=True
        )
        return

    await interaction.response.defer(ephemeral=True)

    # Download file ke path sementara
    tmp_path = "klan_import_tmp.db"
    try:
        await file.save(tmp_path)
    except Exception as e:
        await interaction.followup.send(f"❌ Gagal mengunduh file: {e}", ephemeral=True)
        return

    # Validasi isi: harus SQLite dan punya tabel yang diharapkan
    try:
        test_conn = sqlite3.connect(tmp_path)
        test_cur = test_conn.cursor()
        test_cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tabel = {row[0] for row in test_cur.fetchall()}
        test_conn.close()

        if "anggota" not in tabel:
            os.remove(tmp_path)
            await interaction.followup.send(
                "❌ File bukan database klan yang valid (tabel `anggota` tidak ditemukan).",
                ephemeral=True
            )
            return
    except Exception as e:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        await interaction.followup.send(
            f"❌ File bukan SQLite valid: {e}", ephemeral=True
        )
        return

    # Backup database lama dulu (jaga-jaga)
    try:
        if os.path.exists("klan.db"):
            os.replace("klan.db", "klan_lama.db")
        os.replace(tmp_path, "klan.db")
    except Exception as e:
        await interaction.followup.send(
            f"❌ Gagal mengganti database: {e}", ephemeral=True
        )
        return

    # Reconnect global cursor ke file baru
    global conn, cursor
    conn.close()
    conn = sqlite3.connect("klan.db")
    cursor = conn.cursor()

    # Pastikan skema tabel job ada (kalau file lama belum punya)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS anggota_job (
            discord_id INTEGER,
            job TEXT,
            PRIMARY KEY (discord_id, job)
        )
    ''')
    conn.commit()

    # Hitung isi database baru
    cursor.execute("SELECT COUNT(*) FROM anggota")
    jumlah = cursor.fetchone()[0]

    await interaction.followup.send(
        f"✅ Database berhasil di-restore.\n"
        f"**Jumlah anggota:** {jumlah}\n"
        f"Database lama disimpan sebagai `klan_lama.db` (tidak bisa diakses lewat bot).",
        ephemeral=True
    )

# ====== DAFTAR JOB ======
JOB_EMOJI = {
    "Ahli Bangunan": "🏗️",
    "Boss Penjahit": "🧵",
    "Pakar Alat & Senjata": "⚔️",
    "Penyetok Barang": "📦",
    "Petani": "🧑‍🌾",
    "Supervisor MBG": "🧑‍🍳",
}

DAFTAR_JOB = list(JOB_EMOJI.keys())

CHANNEL_PILIH_JOB_ID = 1559965318691029002


# ====== VIEW: SELECT JOB LANGSUNG DI CHANNEL ======
class PilihJobSelect(discord.ui.Select):
    def __init__(self, guild: discord.Guild):
        options = [
            discord.SelectOption(
                label=nama,
                value=nama,
                emoji=JOB_EMOJI.get(nama, "⚒️"),
            )
            for nama in DAFTAR_JOB
        ]
        super().__init__(
            placeholder="Pilih job kamu di sini...",
            min_values=0,
            max_values=len(DAFTAR_JOB),
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        member = interaction.user
        guild = interaction.guild
        dipilih = set(self.values)
        semua_role_job = set(DAFTAR_JOB)

        # Role job yang saat ini dipegang member
        dimiliki = {r.name for r in member.roles if r.name in semua_role_job}

        tambah = dipilih - dimiliki
        hapus = dimiliki - dipilih

        gagal = []
        for nama in tambah:
            role = discord.utils.get(guild.roles, name=nama)
            if role is None:
                gagal.append(f"{nama} (role tidak ada)")
                continue
            try:
                await member.add_roles(role, reason="Pilih job via menu")
            except discord.Forbidden:
                gagal.append(f"{nama} (izin ditolak)")

        for nama in hapus:
            role = discord.utils.get(guild.roles, name=nama)
            if role is None:
                continue
            try:
                await member.remove_roles(role, reason="Lepas job via menu")
            except discord.Forbidden:
                gagal.append(f"{nama} (izin ditolak)")

        # Simpan ke database (sinkron dengan /daftar)
        cursor.execute("DELETE FROM anggota_job WHERE discord_id = ?", (member.id,))
        for nama in dipilih:
            cursor.execute(
                "INSERT OR IGNORE INTO anggota_job (discord_id, job) VALUES (?, ?)",
                (member.id, nama),
            )
        conn.commit()

        if dipilih:
            teks = f"✅ Job kamu sekarang: **{', '.join(sorted(dipilih))}**"
        else:
            teks = "✅ Semua job kamu sudah dilepas."

        if gagal:
            teks += f"\n⚠️ Sebagian gagal: {', '.join(gagal)}"

        await interaction.followup.send(teks, ephemeral=True)


class PilihJobView(discord.ui.View):
    def __init__(self, guild: discord.Guild):
        super().__init__(timeout=None)   # tidak kedaluwarsa
        self.add_item(PilihJobSelect(guild))


# ====== COMMAND /setupjob ======
@bot.tree.command(name="setupjob", description="Kirim pesan pilih-job (khusus Ketua/Tetua)", guild=discord.Object(id=GUILD_ID))
async def setupjob(interaction: discord.Interaction):
    if not is_admin_klan(interaction.user):
        await interaction.response.send_message(
            "❌ Hanya Ketua/Tetua yang boleh menjalankan ini.", ephemeral=True
        )
        return

    channel = interaction.guild.get_channel(CHANNEL_PILIH_JOB_ID)
    if channel is None:
        await interaction.response.send_message(
            "❌ Channel #pilih-job tidak ditemukan. Cek CHANNEL_PILIH_JOB_ID.",
            ephemeral=True
        )
        return

    try:
        daftar_job_teks = "\n".join(
            f"{emoji} {nama}" for nama, emoji in JOB_EMOJI.items()
        )

        embed = discord.Embed(
            title="⚒️ Pilih Job Kamu",
            description=(
                "Klik dropdown di bawah untuk memilih job kamu.\n"
                "**Bisa pilih lebih dari satu job.**\n\n"
                "Job yang sudah aktif akan tetap terpasang — ubah pilihan kapan saja "
                "dengan membuka dropdown ini lagi.\n\n"
                "**Daftar job:**\n"
                f"{daftar_job_teks}"
            ),
            color=discord.Color.gold(),
        )

        await channel.send(embed=embed, view=PilihJobView(interaction.guild))

        await interaction.response.send_message(
            f"✅ Pesan pilih-job dikirim di {channel.mention}.", ephemeral=True
        )
    except Exception as e:
        print(f"❌ Gagal setupjob: {e}")
        await interaction.response.send_message(
            f"❌ Gagal mengirim pesan pilih-job: {e}", ephemeral=True
        )

# ====== FITUR ALIANSI ======

class AliansiGroup(app_commands.Group):
    def __init__(self):
        super().__init__(name="aliansi", description="Kelola daftar aliansi klan")


aliansi_group = AliansiGroup()


@aliansi_group.command(name="tambah", description="Tambah klan aliansi (khusus Ketua/Tetua)")
@app_commands.describe(
    nama="Nama klan aliansi",
    deskripsi="Deskripsi singkat (opsional)",
    status="Status aliansi (default: Aktif)",
)
async def aliansi_tambah(interaction: discord.Interaction, nama: str, deskripsi: str = "-", status: str = "Aktif"):
    if not is_admin_klan(interaction.user):
        await interaction.response.send_message(
            "❌ Hanya Ketua/Tetua yang boleh menambah aliansi.", ephemeral=True
        )
        return

    try:
        cursor.execute(
            "INSERT INTO aliansi (nama_klan, deskripsi, status) VALUES (?, ?, ?)",
            (nama, deskripsi, status)
        )
        conn.commit()
        await interaction.response.send_message(
            f"✅ Aliansi **{nama}** ditambahkan.\n"
            f"**Status:** {status}\n"
            f"**Deskripsi:** {deskripsi}",
            ephemeral=True
        )
    except sqlite3.IntegrityError:
        await interaction.response.send_message(
            f"⚠️ Aliansi **{nama}** sudah ada di daftar.", ephemeral=True
        )


@aliansi_group.command(name="hapus", description="Hapus klan aliansi (khusus Ketua/Tetua)")
@app_commands.describe(nama="Nama klan aliansi yang dihapus")
async def aliansi_hapus(interaction: discord.Interaction, nama: str):
    if not is_admin_klan(interaction.user):
        await interaction.response.send_message(
            "❌ Hanya Ketua/Tetua yang boleh menghapus aliansi.", ephemeral=True
        )
        return

    cursor.execute("DELETE FROM aliansi WHERE LOWER(nama_klan) = ?", (nama.lower(),))
    conn.commit()

    if cursor.rowcount == 0:
        await interaction.response.send_message(
            f"⚠️ Aliansi **{nama}** tidak ditemukan.", ephemeral=True
        )
    else:
        await interaction.response.send_message(
            f"✅ Aliansi **{nama}** dihapus.", ephemeral=True
        )


@aliansi_group.command(name="daftar", description="Lihat semua aliansi klan")
async def aliansi_daftar(interaction: discord.Interaction):
    cursor.execute("SELECT nama_klan, deskripsi, status, tanggal FROM aliansi ORDER BY nama_klan")
    semua = cursor.fetchall()

    if not semua:
        await interaction.response.send_message(
            "Belum ada aliansi yang terdaftar.", ephemeral=True
        )
        return

    embed = discord.Embed(
        title="🤝 Daftar Aliansi Klan",
        color=discord.Color.teal()
    )
    for nama, deskripsi, status, tgl in semua:
        embed.add_field(
            name=f"{nama} — {status}",
            value=f"{deskripsi}\n*Ditambahkan: {tgl[:10]}*",
            inline=False
        )
    embed.set_footer(text=f"Total: {len(semua)} aliansi")
    await interaction.response.send_message(embed=embed)


@aliansi_group.command(name="edit", description="Edit aliansi (khusus Ketua/Tetua)")
@app_commands.describe(
    nama="Nama klan aliansi yang diedit",
    deskripsi_baru="Deskripsi baru (kosongkan jika tidak diubah)",
    status_baru="Status baru (kosongkan jika tidak diubah)",
)
async def aliansi_edit(interaction: discord.Interaction, nama: str, deskripsi_baru: str = None, status_baru: str = None):
    if not is_admin_klan(interaction.user):
        await interaction.response.send_message(
            "❌ Hanya Ketua/Tetua yang boleh mengedit aliansi.", ephemeral=True
        )
        return

    cursor.execute("SELECT id FROM aliansi WHERE LOWER(nama_klan) = ?", (nama.lower(),))
    if cursor.fetchone() is None:
        await interaction.response.send_message(
            f"⚠️ Aliansi **{nama}** tidak ditemukan.", ephemeral=True
        )
        return

    if deskripsi_baru is not None:
        cursor.execute("UPDATE aliansi SET deskripsi = ? WHERE LOWER(nama_klan) = ?", (deskripsi_baru, nama.lower()))
    if status_baru is not None:
        cursor.execute("UPDATE aliansi SET status = ? WHERE LOWER(nama_klan) = ?", (status_baru, nama.lower()))
    conn.commit()

    await interaction.response.send_message(
        f"✅ Aliansi **{nama}** diperbarui.", ephemeral=True
    )


bot.tree.add_command(aliansi_group, guild=discord.Object(id=GUILD_ID))

# ====== FITUR PENGUMUMAN (satu channel) ======

def role_pengumuman_user(member: discord.Member) -> str | None:
    """Kembalikan nama role yang diizinkan, atau None."""
    nama_role = {r.name for r in member.roles}
    if member.guild and member.guild.owner and member.id == member.guild.owner.id:
        return "owner"
    for role in ["Wakil Rakyat", "Budak Member"]:
        if role in nama_role:
            return role
    return None


@bot.tree.command(name="umumkan", description="Kirim pengumuman ke channel pengumuman", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(
    pesan="Isi pengumuman",
    judul="Judul pengumuman (opsional)",
)

CHANNEL_PENGUMUMAN_ID = 1559960943465861120

async def umumkan(interaction: discord.Interaction, pesan: str, judul: str = "📢 Pengumuman"):
    role_asal = role_pengumuman_user(interaction.user)
    if role_asal is None:
        await interaction.response.send_message(
            "❌ Kamu tidak punya role yang diizinkan membuat pengumuman.\n"
            "Role yang diizinkan: **Wakil Rakyat**, **Budak Member**, atau **Owner**.",
            ephemeral=True
        )
        return

    if not CHANNEL_PENGUMUMAN_ID:
        await interaction.response.send_message(
            "❌ Channel pengumuman belum diatur.\n"
            "Ketua/Tetua perlu mengisi `CHANNEL_PENGUMUMAN_ID` pada kode bot.",
            ephemeral=True
        )
        return

    channel = interaction.guild.get_channel(CHANNEL_PENGUMUMAN_ID)
    if channel is None:
        await interaction.response.send_message(
            f"❌ Channel dengan ID `{CHANNEL_PENGUMUMAN_ID}` tidak ditemukan di server.",
            ephemeral=True
        )
        return

    embed = discord.Embed(
        title=judul,
        description=pesan,
        color=discord.Color.orange(),
        timestamp=datetime.now()
    )
    embed.set_author(
        name=interaction.user.display_name,
        icon_url=interaction.user.display_avatar.url
    )
    embed.set_footer(text=f"Dikirim oleh {role_asal}")

    try:
        await channel.send(embed=embed)
        await interaction.response.send_message(
            f"✅ Pengumuman terkirim ke {channel.mention}.", ephemeral=True
        )
    except discord.Forbidden:
        await interaction.response.send_message(
            f"❌ Bot tidak punya izin mengirim pesan di {channel.mention}.", ephemeral=True
        )

@bot.tree.command(name="umumkan", description="Kirim pengumuman ke channel role kamu", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(
    pesan="Isi pengumuman",
    judul="Judul pengumuman (opsional)",
)
# ====== JALANKAN BOT ======
bot.run(TOKEN)