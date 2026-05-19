import os
import asyncio
import aiohttp
import json
from datetime import datetime, timedelta
import discord
from discord.ext import commands
from discord.commands import SlashCommandGroup, slash_command
from urllib.parse import urlencode

# Initialize bot with intents
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="/", intents=intents)

# Store active sessions (username -> session_data)
SESSIONS = {}
SESSION_TIMEOUT = 3600  # 1 hour

class NitroTypeClient:
    """Client for Nitro Type API"""
    BASE_URL = "https://www.nitrotype.com/api/"
    
    def __init__(self, username: str, password: str):
        self.username = username
        self.password = password
        self.cookies = {}
        self.session = None
        self.created_at = datetime.now()
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def login(self) -> bool:
        """Authenticate with Nitro Type API"""
        try:
            async with aiohttp.ClientSession() as session:
                data = {
                    'username': self.username,
                    'password': self.password
                }
                
                async with session.post(
                    f"{self.BASE_URL}login",
                    data=data
                ) as resp:
                    if resp.status == 200:
                        # Extract and store cookies
                        for cookie_header in resp.headers.getall('Set-Cookie', []):
                            parts = cookie_header.split(';')[0]
                            if '=' in parts:
                                key, value = parts.split('=', 1)
                                self.cookies[key.strip()] = value.strip()
                        return True
                    return False
        except Exception as e:
            print(f"Login error: {e}")
            return False
    
    async def get(self, path: str, params: dict = None) -> dict:
        """Make GET request to API"""
        try:
            if not self.session:
                self.session = aiohttp.ClientSession()
            
            url = f"{self.BASE_URL}{path}"
            headers = {'Cookie': '; '.join([f"{k}={v}" for k, v in self.cookies.items()])}
            
            async with self.session.get(url, headers=headers, params=params) as resp:
                if resp.status == 200:
                    return await resp.json()
                return {"error": f"Status {resp.status}"}
        except Exception as e:
            return {"error": str(e)}
    
    async def post(self, path: str, data: dict = None) -> dict:
        """Make POST request to API"""
        try:
            if not self.session:
                self.session = aiohttp.ClientSession()
            
            url = f"{self.BASE_URL}{path}"
            headers = {'Cookie': '; '.join([f"{k}={v}" for k, v in self.cookies.items()])}
            
            async with self.session.post(url, headers=headers, data=data) as resp:
                if resp.status == 200:
                    return await resp.json()
                return {"error": f"Status {resp.status}"}
        except Exception as e:
            return {"error": str(e)}
    
    async def get_player_stats(self) -> dict:
        """Get player statistics"""
        return await self.get("stats/summary")
    
    async def claim_daily_reward(self) -> dict:
        """Claim daily reward"""
        return await self.post("rewards/daily")
    
    def is_expired(self) -> bool:
        """Check if session is expired"""
        return datetime.now() - self.created_at > timedelta(seconds=SESSION_TIMEOUT)


def create_panel_embed(username: str, stats: dict) -> discord.Embed:
    """Create a nice embed for the panel"""
    embed = discord.Embed(
        title=f"📊 Nitro Type Panel - {username}",
        color=discord.Color.blue()
    )
    
    if "error" not in stats:
        stats_data = stats.get("data", {})
        embed.add_field(
            name="Stats",
            value=f"**Races:** {stats_data.get('races', 'N/A')}\n"
                  f"**Speed:** {stats_data.get('avgSpeed', 'N/A')} WPM\n"
                  f"**Accuracy:** {stats_data.get('avgAccuracy', 'N/A')}%",
            inline=False
        )
        
        embed.add_field(
            name="Level",
            value=str(stats_data.get('level', 'N/A')),
            inline=True
        )
        
        embed.add_field(
            name="Cash",
            value=f"${stats_data.get('money', 'N/A')}",
            inline=True
        )
    else:
        embed.add_field(
            name="Error",
            value=f"Failed to load stats: {stats.get('error', 'Unknown error')}",
            inline=False
        )
    
    embed.set_footer(text=f"Session expires in {SESSION_TIMEOUT // 60} minutes")
    embed.timestamp = datetime.now()
    
    return embed


async def create_panel_view(username: str) -> discord.ui.View:
    """Create interactive view for panel"""
    view = discord.ui.View()
    
    async def refresh_callback(interaction: discord.Interaction):
        await interaction.response.defer()
        
        if username not in SESSIONS:
            await interaction.followup.send("❌ Session expired. Please login again.", ephemeral=True)
            return
        
        client = SESSIONS[username]['client']
        if client.is_expired():
            del SESSIONS[username]
            await interaction.followup.send("❌ Session expired. Please login again.", ephemeral=True)
            return
        
        stats = await client.get_player_stats()
        embed = create_panel_embed(username, stats)
        await interaction.followup.send(embed=embed, ephemeral=True)
    
    async def reward_callback(interaction: discord.Interaction):
        await interaction.response.defer()
        
        if username not in SESSIONS:
            await interaction.followup.send("❌ Session expired. Please login again.", ephemeral=True)
            return
        
        client = SESSIONS[username]['client']
        if client.is_expired():
            del SESSIONS[username]
            await interaction.followup.send("❌ Session expired. Please login again.", ephemeral=True)
            return
        
        result = await client.claim_daily_reward()
        
        if "error" in result:
            await interaction.followup.send(f"❌ Error: {result['error']}", ephemeral=True)
        else:
            reward_data = result.get("data", {})
            embed = discord.Embed(
                title="🎁 Daily Reward Claimed!",
                description=f"**Reward:** {reward_data.get('type', 'N/A').upper()}",
                color=discord.Color.green()
            )
            embed.add_field(
                name="Amount",
                value=f"${reward_data.get('value', 0):,}",
                inline=False
            )
            embed.add_field(
                name="Next Reward",
                value=f"In {reward_data.get('next', 0) // 3600} hours",
                inline=False
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    async def logout_callback(interaction: discord.Interaction):
        await interaction.response.defer()
        
        if username in SESSIONS:
            if SESSIONS[username]['client'].session:
                await SESSIONS[username]['client'].session.close()
            del SESSIONS[username]
        
        await interaction.followup.send("✅ Logged out successfully!", ephemeral=True)
    
    # Create buttons
    refresh_btn = discord.ui.Button(label="🔄 Refresh Stats", style=discord.ButtonStyle.primary)
    refresh_btn.callback = refresh_callback
    view.add_item(refresh_btn)
    
    reward_btn = discord.ui.Button(label="🎁 Claim Daily Reward", style=discord.ButtonStyle.success)
    reward_btn.callback = reward_callback
    view.add_item(reward_btn)
    
    logout_btn = discord.ui.Button(label="🚪 Logout", style=discord.ButtonStyle.danger)
    logout_btn.callback = logout_callback
    view.add_item(logout_btn)
    
    return view


@bot.event
async def on_ready():
    print(f"✅ Bot is online as {bot.user}")


@slash_command(description="Nitro Type account management panel")
async def panel(
    ctx: discord.ApplicationContext,
    action: discord.Option(str, choices=["login", "view", "logout"], description="Panel action") = "view",
    username: discord.Option(str, description="Nitro Type username (required for login)", required=False) = None,
    password: discord.Option(str, description="Nitro Type password (required for login, hidden input)", required=False) = None
):
    """Main panel command for Nitro Type"""
    
    user_id = ctx.author.id
    
    if action == "login":
        # Validate inputs
        if not username or not password:
            embed = discord.Embed(
                title="❌ Login Failed",
                description="Username and password are required for login.",
                color=discord.Color.red()
            )
            await ctx.respond(embed=embed, ephemeral=True)
            return
        
        await ctx.response.defer(ephemeral=True)
        
        # Attempt login
        try:
            client = NitroTypeClient(username, password)
            success = await client.login()
            
            if success:
                client.session = aiohttp.ClientSession()
                
                # Store session
                SESSIONS[username] = {
                    'client': client,
                    'user_id': user_id,
                    'created_at': datetime.now()
                }
                
                # Get initial stats
                stats = await client.get_player_stats()
                
                embed = discord.Embed(
                    title="✅ Login Successful!",
                    description=f"Logged in as **{username}**",
                    color=discord.Color.green()
                )
                embed.add_field(
                    name="Session ID",
                    value=f"`{username}`",
                    inline=False
                )
                embed.add_field(
                    name="Expires In",
                    value=f"{SESSION_TIMEOUT // 60} minutes",
                    inline=False
                )
                
                view = await create_panel_view(username)
                stats_embed = create_panel_embed(username, stats)
                
                await ctx.followup.send(embed=embed, ephemeral=True)
                await ctx.followup.send(embed=stats_embed, view=view, ephemeral=True)
            else:
                embed = discord.Embed(
                    title="❌ Login Failed",
                    description="Invalid username or password.",
                    color=discord.Color.red()
                )
                await ctx.followup.send(embed=embed, ephemeral=True)
        
        except Exception as e:
            embed = discord.Embed(
                title="❌ Login Error",
                description=f"An error occurred: {str(e)}",
                color=discord.Color.red()
            )
            await ctx.followup.send(embed=embed, ephemeral=True)
    
    elif action == "view":
        await ctx.response.defer(ephemeral=True)
        
        # Find active sessions for this user
        active_sessions = [s for s in SESSIONS.values() if s['user_id'] == user_id and not s['client'].is_expired()]
        
        if not active_sessions:
            embed = discord.Embed(
                title="❌ No Active Sessions",
                description="You don't have any active Nitro Type sessions. Use `/panel login` to create one.",
                color=discord.Color.red()
            )
            await ctx.followup.send(embed=embed, ephemeral=True)
            return
        
        # Display first session
        session = active_sessions[0]
        client = session['client']
        
        stats = await client.get_player_stats()
        embed = create_panel_embed(client.username, stats)
        
        view = await create_panel_view(client.username)
        await ctx.followup.send(embed=embed, view=view, ephemeral=True)
    
    elif action == "logout":
        await ctx.response.defer(ephemeral=True)
        
        # Find and logout all sessions for this user
        sessions_to_remove = [username for username, session in SESSIONS.items() if session['user_id'] == user_id]
        
        if not sessions_to_remove:
            embed = discord.Embed(
                title="❌ No Active Sessions",
                description="You don't have any active sessions to logout from.",
                color=discord.Color.red()
            )
            await ctx.followup.send(embed=embed, ephemeral=True)
            return
        
        for session_username in sessions_to_remove:
            if SESSIONS[session_username]['client'].session:
                await SESSIONS[session_username]['client'].session.close()
            del SESSIONS[session_username]
        
        embed = discord.Embed(
            title="✅ Logged Out",
            description=f"Successfully logged out {len(sessions_to_remove)} session(s).",
            color=discord.Color.green()
        )
        await ctx.followup.send(embed=embed, ephemeral=True)


# Cleanup expired sessions periodically
@tasks.loop(minutes=5)
async def cleanup_sessions():
    """Remove expired sessions"""
    expired = [username for username, session in SESSIONS.items() if session['client'].is_expired()]
    for username in expired:
        if SESSIONS[username]['client'].session:
            await SESSIONS[username]['client'].session.close()
        del SESSIONS[username]
    
    if expired:
        print(f"🧹 Cleaned up {len(expired)} expired session(s)")


# Import tasks for the cleanup loop
from discord.ext import tasks

cleanup_sessions.start()


# Run the bot
if __name__ == "__main__":
    TOKEN = os.getenv("DISCORD_TOKEN")
    
    if not TOKEN:
        print("❌ Error: DISCORD_TOKEN environment variable not set!")
        print("Set it with: export DISCORD_TOKEN='your_token_here'")
        exit(1)
    
    try:
        bot.run(TOKEN)
    except Exception as e:
        print(f"❌ Failed to start bot: {e}")
