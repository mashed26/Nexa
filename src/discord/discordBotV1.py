# discordBotV1.py
# Under the MIT License.
# This is the first version of NexaBot. It is now deprecated and no longer maintained, but is left in the codebase for future reference. For the current version of the bot, see discordBotV2.py.

import os
from pathlib import Path
from venv import logger

import discord
from discord.ext import commands
from discord import app_commands, Interaction, TextChannel

from backend.instanceManager import InstanceManager, ServerStatus, ServerInstance
from services.nexaConfig import NexaConfig, NexaInstanceRegistry

from services.nexaDB import unprotectedDB, protectedDB
import json

from datetime import datetime, timezone
import asyncio

from dataclasses import dataclass
from typing import Callable, Optional, Awaitable, List
import inspect

from services import nexaLoggerFactory

@dataclass
class MenuButton:
    label: str
    callback: Callable[[Interaction, "SimpleMenu"], Awaitable | None]
    style: discord.ButtonStyle = discord.ButtonStyle.secondary
    emoji: str | None = None
    disabled: bool = False
    row: int | None = None

@dataclass
class MenuPage:
    title: str
    description: str
    on_enter: Optional[Callable[[Interaction, "SimpleMenu"], Awaitable | None]] = None
    buttons: Optional[list[tuple[str, Callable[[Interaction, "SimpleMenu"], Awaitable | None]]]] = None

class SimpleMenu(discord.ui.View):
    def __init__(self, owner: discord.User, *, timeout: int = 300, ephemeral: bool = True):
        super().__init__(timeout=timeout)
        self.owner = owner
        self.pages: List[MenuPage] = []
        self.index = 0
        self.ephemeral = ephemeral
        self.message: Optional[discord.Message] = None

        self._dynamic_buttons: List[discord.ui.Button] = []

    # -----------------------
    # Public API
    # -----------------------

    def add_page(self, *, title: str, description: str,
                 on_enter=None,
                 buttons: Optional[List[MenuButton]] = None):
        self.pages.append(MenuPage(title, description, on_enter, buttons))
        return self

    async def send(self, interaction: Interaction):
        self._build_page()
        await interaction.response.send_message(
            embed=self._embed(),
            view=self,
            ephemeral=self.ephemeral
        )
        self.message = await interaction.original_response()
        await self._run_on_enter(interaction)

    async def refresh(self, interaction: Interaction):
        """Rebuild current page UI and edit message."""
        self._build_page()
        await interaction.response.edit_message(
            embed=self._embed(),
            view=self
        )

    # -----------------------
    # Internal Mechanics
    # -----------------------

    def _embed(self) -> discord.Embed:
        page = self.pages[self.index]
        embed = discord.Embed(
            title=page.title,
            description=page.description,
            color=0x5865F2
        )
        embed.set_footer(text=f"Page {self.index + 1}/{len(self.pages)} • Nexabot")
        return embed

    async def _run_on_enter(self, interaction: Interaction):
        page = self.pages[self.index]
        if page.on_enter:
            result = page.on_enter(interaction, self)
            if inspect.isawaitable(result):
                await result

    async def interaction_check(self, interaction: Interaction) -> bool:
        if interaction.user != self.owner:
            await interaction.response.send_message(
                "This menu isn't yours.",
                ephemeral=True
            )
            return False
        return True

    def _clear_dynamic_buttons(self):
        for button in list(self._dynamic_buttons):
            try:
                self.remove_item(button)
            except Exception:
                pass
        self._dynamic_buttons.clear()

    def _build_page(self):
        self._clear_dynamic_buttons()

        if not self.pages:
            return

        page = self.pages[self.index]
        if not page.buttons:
            return

        for btn_model in page.buttons:
            button = discord.ui.Button(
                label=btn_model.label,
                style=btn_model.style,
                emoji=btn_model.emoji,
                disabled=btn_model.disabled,
                row=btn_model.row
            )

            async def callback(interaction: Interaction, model=btn_model):
                try:
                    result = model.callback(interaction, self)
                    if inspect.isawaitable(result):
                        await result
                except Exception as e:
                    try:
                        await interaction.response.send_message(
                            f"Error: {e}",
                            ephemeral=True
                        )
                    except Exception:
                        pass

            button.callback = callback
            self.add_item(button)
            self._dynamic_buttons.append(button)

    # -----------------------
    # Navigation
    # -----------------------

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary, row=4)
    async def back(self, interaction: Interaction, _):
        self.index = (self.index - 1) % len(self.pages)
        self._build_page()
        await interaction.response.edit_message(embed=self._embed(), view=self)
        await self._run_on_enter(interaction)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary, row=4)
    async def next(self, interaction: Interaction, _):
        self.index = (self.index + 1) % len(self.pages)
        self._build_page()
        await interaction.response.edit_message(embed=self._embed(), view=self)
        await self._run_on_enter(interaction)


class ServerStatusEmbed:
    def __init__(self, instance: ServerInstance):
        self.instance = instance

    def build(self) -> discord.Embed:
        color_map = {
            ServerStatus.ONLINE: 0x57F287,
            ServerStatus.STARTING: 0xFEE75C,
            ServerStatus.OFFLINE: 0xED4245
        }
        color = color_map.get(self.instance.status, 0x5865F2)

        embed = discord.Embed(
            title=f"Server Status: {self.instance.name}",
            color=color,
            timestamp=datetime.now(timezone.utc)
        )

        embed.add_field(name="Status", value=self.instance.status.value.capitalize(), inline=True)
        embed.add_field(name="Players", value=f"{self.instance.players}/{self.instance.max_players}", inline=True)
        embed.add_field(name="Version", value=self.instance.version, inline=True)
        embed.add_field(name="Modloader", value=self.instance.loader, inline=True)

        if self.instance.icon_url:
            embed.set_thumbnail(url=self.instance.icon_url)

        embed.set_footer(text="Nexabot V2")

        return embed


class DiscordBot:
    """
    DiscordBot integrates with NexaConfig and NexaInstanceRegistry.
    Constructor args:
      - token: BOT token
      - instance_manager: InstanceManager (should be provided)
      - registry: optional NexaInstanceRegistry or path string
      - config: optional NexaConfig or path string
      - statusChannelID: optional int; if omitted, will try to read from config at 'discord.statusChannel'
    """
    def __init__(
        self,
        token: str,
        instance_manager: InstanceManager,
        *,
        registry: NexaInstanceRegistry | str | None = None,
        config: NexaConfig | str | None = None,
        statusChannelID: int | None = None
    ):  
        self.logger = nexaLoggerFactory.get_logger("NexaBot")
        self.logger.info("Initializing Discord bot.")
        self.token = token
        self.instance_manager = instance_manager

        self.instancesAvailable = registry.list_instances()

        # Load config object if needed
        if isinstance(config, NexaConfig):
            self.config = config
        else:
            cfg_path = config if isinstance(config, str) else "NexaBotConfig.yaml"
            self.config = NexaConfig(cfg_path)

        # Load registry object if needed
        if isinstance(registry, NexaInstanceRegistry):
            self.registry = registry
        else:
            reg_path = registry if isinstance(registry, str) else "NexaInstanceRegistry.yaml"
            self.registry = NexaInstanceRegistry(reg_path)

        # Ensure instance manager has instances registered (populate if empty)
        self._hydrate_instances_from_registry_if_needed()

        # Resolve status channel id
        self.statusChannelID = statusChannelID or self.config.get("discord.statusChannel", None)

        # Bot and intents
        intents = discord.Intents.default()
        intents.message_content = False
        self.bot = commands.Bot(command_prefix="/", intents=intents)

        # Internal state
        self._register_events()
        self._register_commands()

        # Protected DB setup
        db_key = os.environ.get("NEXABOT_PROTECTED_KEY", None)
        if not db_key:
            self.logger.error("Environment variable 'NEXABOT_PROTECTED_KEY' is not set. This is REQUIRED for the bot to run. The fact that you are seeing this error means something went very wrong with the early stability checks. Exiting now to prevent further issues.")
            raise ValueError("NEXABOT_PROTECTED_KEY environment variable is not set. This is REQUIRED for the bot to run.")

        self.userData = protectedDB(dbPath=Path("databases") / "userData.nxdb", password=db_key, create_if_missing=True)

        # update interval (seconds)
        self.updateInterval = int(self.config.get("general.updateInterval", 10))

    def _isUserAgreedToTerms(self, user_id: int) -> bool:
        self.userData.load()
        exists = self.userData.fetchEntry(str(user_id)) is not None
        self.userData.unload()
        return exists

    def _hydrate_instances_from_registry_if_needed(self):
        # If instance_manager already has instances, do nothing.
        if self.instance_manager.instances:
            return

        # Populate from registry
        try:
            instance_names = self.registry.list_instances()
        except Exception:
            instance_names = list((self.registry._data.get("instances") or {}).keys()) if getattr(self.registry, "_data", None) else []

        instances_root = Path.cwd() / Path(self.config.get("general.instancesFolder", "instances"))

        for name in instance_names:
            try:
                inst_cfg = self.registry.get_instance(name) or {}
                folder = inst_cfg.get("folder") or str(instances_root / name)
                version = inst_cfg.get("version", "")
                loader = inst_cfg.get("loaderType") or inst_cfg.get("loader") or ""
                icon_url = inst_cfg.get("icon_url") or inst_cfg.get("icon") or None

                self.instance_manager.add_instance(ServerInstance(
                    name=name,
                    folder=folder,
                    version=version,
                    loader=loader,
                    icon_url=icon_url
                ))
                self.logger.info(f"Registered instance '{name}' -> {folder}")
            except Exception as e:
                self.logger.error(f"Failed to register instance '{name}': {e}")

    def _register_events(self):
        @self.bot.event
        async def on_ready():
            #print("onready called")
            self.logger.info(f"Logged in as {self.bot.user}")
            #print("should have logged")
            try:
                synced = await self.bot.tree.sync()
                self.logger.info(f"Synced {len(synced)} command(s)")
            except Exception as e:
                self.logger.error(f"Error occurred while syncing commands: {e}")

            # Start instance manager background status loop
            await self.instance_manager.start()

            activity = discord.Activity(type=discord.ActivityType.playing, name="NexaBot v2.0.0-Stable")
            await self.bot.change_presence(status=discord.Status.online, activity=activity)

            # Spawn live status loop
            asyncio.create_task(self.start_live_status_loop())

    def _register_commands(self):
        async def _check_terms(interaction: Interaction) -> bool:
            if not self._isUserAgreedToTerms(interaction.user.id):
                menu = SimpleMenu(interaction.user)

                async def _handle_terms_response(interaction: Interaction, menu: SimpleMenu):
                    self.userData.load()
                    self.userData.setEntry(str(interaction.user.id), {
                        "minecraftUser": None,
                        "authorizedNexusApps": [],
                        "privacySettings": {}
                    })
                    self.userData.unload()

                    await interaction.response.edit_message(
                        content="Thank you for agreeing to the terms! You can now use the bot's features. If you want to review or manage your data, use the `/userdata` command. Please re-run your previous command.",
                        embed=None,
                        view=None
                    )

                async def _handle_terms_response_decline(interaction: Interaction, menu: SimpleMenu):
                    await interaction.response.edit_message(
                        content="We understand. You can re-run any command to see the agreement again.",
                        embed=None,
                        view=None
                    )

                menu.add_page(
                    title="Terms of Service",
                    description=(
                        "In order to use NexaBot, you must agree to your use of data. Here is what we'll generally do:\n\n"
                        "- Store a mapping of your Discord ID to any Minecraft accounts you link, so that we can show your Minecraft username in the server status and use it for any Minecraft-related features.\n"
                        "- Store a list of any Nexus Mods applications you authorize, so that we can show it in the user data section and use it for any app-related features.\n"
                        "- Store any privacy settings you configure, so that we can respect them when handling your data.\n\n"
                        "The data you provide us is securely handled in an encrypted database, and is never shared with a third party that is not presented to you.\n"
                        "Data is only used for providing features within the bot. Generally, the data you would provide Mojang is similarly accessed by NexaBot for the same purposes.\n\n"
                        "If you find these terms acceptable, and would like to agree to them, click the 'I Agree' button shown below.\n"
                    ),
                    buttons=[
                        MenuButton(label="I Agree", style=discord.ButtonStyle.success, callback=_handle_terms_response),
                        MenuButton(label="I Do Not Agree", style=discord.ButtonStyle.danger, callback=_handle_terms_response_decline)
                    ]
                )

                await menu.send(interaction)
                return False
            return True

        @app_commands.command(name="ping", description="Tests the bot")
        async def ping_command(interaction: Interaction):
            if not await _check_terms(interaction):
                return
            print("Pinged")
            await interaction.response.send_message(f"Latency: {self.bot.latency:.2f}s ")

        @app_commands.command(name="refresh_cmds", description="Tricks Discord into refreshing commands for a client")
        async def refresh_cmds_command(interaction: Interaction):
            await interaction.response.send_message("Commands up to date. 2")

        @app_commands.command(name="status", description="Shows server stats")
        async def status_command(interaction: Interaction):
            if not await _check_terms(interaction):
                return
            instance = self.instance_manager.get_primary_instance()
            if not instance:
                await interaction.response.send_message("No server instance is configured", ephemeral=True)
                return

            status_embed = ServerStatusEmbed(instance).build()

            menu = SimpleMenu(interaction.user)

            menu.add_page(
                title=status_embed.title,
                description=(
                    f"**Status:** {instance.status.value.capitalize()}\n"
                    f"**Players:** {instance.players}/{instance.max_players}\n"
                    f"**Version:** {instance.version}\n"
                    f"**Modloader:** {instance.loader}"
                )
            )

            async def controls_page(_interaction, _menu=None):
                pass

            menu.add_page(
                title="Usage",
                description="• `/start`: Start the server\n• `/stop`: Stop the server\n\n",
                on_enter=controls_page
            )

            menu.add_page(
                title="Diagnostics",
                description=(
                    f"**Instance Name:** {instance.name}\n"
                    f"**Status Channel:** {f'<#{self.statusChannelID}>' if self.statusChannelID else 'not configured'}\n"
                    f"**Update Interval:** {self.updateInterval}s"
                )
            )

            await menu.send(interaction)

        @app_commands.command(name="userdata", description="Show and manage your user data stored by NexaBot.")
        async def userdata_command(interaction: Interaction):
            if not await _check_terms(interaction):
                return

            instance = self.instance_manager.get_primary_instance()
            if not instance:
                await interaction.response.send_message(
                    "No server instance is configured", ephemeral=True
                )
                return

            self.userData.load()
            user_data = self.userData.fetchEntry(f"{interaction.user.id}") or {}
            self.userData.unload()

            menu = SimpleMenu(interaction.user)

            menu.add_page(
                title="Introduction",
                description=(
                    "This section allows you to view and manage your user data stored by NexaBot.\n\n"
                    "The following pages will allow you to see what data is stored, and perform data management actions."
                )
            )

            minecraftUser = user_data.get("minecraftUser", "Not linked")

            menu.add_page(
                title="Basic Data",
                description=(
                    f"Below is the data you've authorized NexaBot and the Operator to use:\n\n"
                    f"**Minecraft Username:** {minecraftUser}\n"
                    f"**User ID:** {interaction.user.id}\n\n"
                )
            )

            authedApps = user_data.get("authorizedNexusApps", [])

            menu.add_page(
                title="Authorized Nexus Applications",
                description=(
                    f"Below are the applications you've authorized NexaBot and the Operator to use:\n\n"
                    + ("\n".join(f"- {app}" for app in authedApps) if authedApps else "You have not authorized any applications.")
                )
            )

            privacySettings = user_data.get("privacySettings", {})

            async def remove_privacy_setting(interaction: Interaction, menu: SimpleMenu):
                data = self.userData

                class RemoveSettingModal(discord.ui.Modal, title="Remove Privacy Setting"):
                    setting_name = discord.ui.TextInput(
                        label="Setting Name",
                        placeholder="e.g. abstractIdentifiers",
                        required=True
                    )

                    async def on_submit(self, interaction: Interaction):
                        setting_to_remove = self.setting_name.value.strip()
                        if setting_to_remove in privacySettings:
                            del privacySettings[setting_to_remove]
                            data.load()
                            entry = data.fetchEntry(f"{interaction.user.id}") or {}
                            entry["privacySettings"] = privacySettings
                            data.setEntry(f"{interaction.user.id}", entry)
                            data.unload()
                            await interaction.response.send_message(
                                f"Removed privacy setting `{setting_to_remove}`.", ephemeral=True
                            )
                        else:
                            await interaction.response.send_message(
                                f"Privacy setting `{setting_to_remove}` not found.", ephemeral=True
                            )

                await interaction.response.send_modal(RemoveSettingModal())

            menu.add_page(
                title="Privacy Settings",
                description=(
                    f"You have told NexaBot to use these privacy settings when handling your data:\n\n"
                    + ("\n".join(f"- {k}: {v}" for k, v in privacySettings.items()) if privacySettings else "You have not set any privacy settings.")
                ),
                buttons=[
                    MenuButton(
                        label="Remove Setting",
                        style=discord.ButtonStyle.danger,
                        callback=remove_privacy_setting
                    )
                ]
            )

            await menu.send(interaction)

        @app_commands.command(name="start", description="Starts the primary server instance.")
        async def start_command(interaction: Interaction):
            if not await _check_terms(interaction):
                return

            instance = self.instance_manager.get_primary_instance()
            if not instance:
                await interaction.response.send_message("No primary server instance is configured.", ephemeral=True)
                return

            if instance.status == ServerStatus.ONLINE or instance.status == ServerStatus.STARTING:
                await interaction.response.send_message(f"Server `{instance.name}` is already {instance.status.value}.", ephemeral=True)
                return

            await interaction.response.send_message(f"Starting server `{instance.name}`", ephemeral=True)
            asyncio.create_task(self._start_instance_task(instance))


        @app_commands.command(name="start_specific", description="Starts the specified instance.")
        @app_commands.describe(instance="The specific instance you want to start up")
        @app_commands.choices(instance=[
            app_commands.Choice(name=inst_name, value=inst_name) for inst_name in self.instancesAvailable
        ])
        async def startSpecific_command(interaction: Interaction, instance: app_commands.Choice[str]):
            if not await _check_terms(interaction):
                return

            tgtInstance = self.instance_manager.get_instance(instance.value)

            if tgtInstance.status == ServerStatus.ONLINE or tgtInstance.status == ServerStatus.STARTING:
                await interaction.response.send_message(f"Server `{tgtInstance.name}` is already {tgtInstance.status.value}.", ephemeral=True)
                return
            
            await interaction.response.send_message(f"Starting server `{tgtInstance.name}`", ephemeral=True)
            asyncio.create_task(self._start_instance_task(tgtInstance))

        @app_commands.command(name="stop", description="Stops the server instance")
        async def stop_command(interaction: Interaction):
            if not await _check_terms(interaction):
                return

            instance = self.instance_manager.get_primary_instance()
            if not instance:
                await interaction.response.send_message("No server instance is configured.", ephemeral=True)
                return

            await interaction.response.send_message(f"Stopping server `{instance.name}`…", ephemeral=True)

            channel: TextChannel | None = self.bot.get_channel(self.statusChannelID) if self.statusChannelID else None
            status_msg = None
            if channel:
                messages = [msg async for msg in channel.history(limit=10)]
                for msg in messages:
                    if msg.author == self.bot.user:
                        status_msg = msg
                        break

            async def update_embed(instance: ServerInstance):
                if status_msg:
                    embed = ServerStatusEmbed(instance).build()
                    await status_msg.edit(embed=embed)

            asyncio.create_task(self.instance_manager.stop_instance(instance.name, update_embed_callback=update_embed))

        @app_commands.command(name="config", description="SUPERUSER-ONLY. View configs on the server.")
        @app_commands.describe(config_key="The name of the file you want to view.")
        @app_commands.choices(config_key=[
            app_commands.Choice(name="NexaBotConfig.yaml", value="NexaBotConfig"),
            app_commands.Choice(name="NexaInstanceRegistry.yaml", value="NexaInstanceRegistry")
        ])
        async def config_command(interaction: Interaction, config_key: app_commands.Choice[str]):
            if not await _check_terms(interaction):
                return

            requestingUserID = interaction.user.id
            superUserList = self.config.get("discord.superUsers")

            if self.config.get("discord.enableSuperUsers") and requestingUserID in superUserList:
                if config_key.value == "NexaBotConfig":
                    cfg = self.config
                elif config_key.value == "NexaInstanceRegistry":
                    cfg = self.registry

                data = cfg.dumpData()

                embed = discord.Embed(
                    title=f"{config_key.name} Contents",
                    description=f"```yaml\n{json.dumps(data, indent=2)}\n```",
                    color=0x5865F2
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message("You are not a super user, and are unable to view the config files", ephemeral=True)
                return

        @app_commands.command(name="stop_specific", description="Stops the specified instance.")
        @app_commands.describe(instance="The specific instance you want to stop")
        @app_commands.choices(instance=[
            app_commands.Choice(name=inst_name, value=inst_name) for inst_name in self.instance_manager.instances.keys()
        ])
        async def stopSpecific_command(interaction: Interaction, instance: app_commands.Choice[str]):
            if not await _check_terms(interaction):
                return

            tgtInstance = self.instance_manager.get_instance(instance.value)
            if not tgtInstance:
                await interaction.response.send_message(f"Instance `{instance.value}` not found.", ephemeral=True)
                return

            if tgtInstance.status in (ServerStatus.OFFLINE, ServerStatus.SLEEPING):
                await interaction.response.send_message(f"Server `{tgtInstance.name}` is already {tgtInstance.status.value}.", ephemeral=True)
                return

            await interaction.response.send_message(f"Stopping server `{tgtInstance.name}`…", ephemeral=True)
            asyncio.create_task(self.instance_manager.stop_instance(tgtInstance.name))

        @app_commands.command(name="execute", description="SUPERUSER-ONLY. Execute a raw RCON command on an instance.")
        @app_commands.describe(
            instance="The instance to run the command on",
            command="The RCON command to execute"
        )
        @app_commands.choices(instance=[
            app_commands.Choice(name=inst_name, value=inst_name) for inst_name in self.instance_manager.instances.keys()
        ])
        async def execute_command(interaction: Interaction, instance: app_commands.Choice[str], command: str):
            if not await _check_terms(interaction):
                return

            requestingUserID = interaction.user.id
            superUserList = self.config.get("discord.superUsers")

            if not (self.config.get("discord.enableSuperUsers") and requestingUserID in superUserList):
                await interaction.response.send_message("You are not a super user and cannot execute raw commands.", ephemeral=True)
                return

            tgtInstance = self.instance_manager.get_instance(instance.value)
            if not tgtInstance:
                await interaction.response.send_message(f"Instance `{instance.value}` not found.", ephemeral=True)
                return

            try:
                loop = asyncio.get_running_loop()
                response = await loop.run_in_executor(None, tgtInstance.executeCommand, command)
                embed = discord.Embed(
                    title=f"RCON Response: {tgtInstance.name}",
                    description=f"**Command:** `{command}`**Response:**```{response}```",
                    color=0x5865F2
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
            except RuntimeError as e:
                await interaction.response.send_message(f"Error: {e}", ephemeral=True)

        # Register commands on the tree
        self.bot.tree.add_command(ping_command)

        self.bot.tree.add_command(status_command)

        self.bot.tree.add_command(start_command)
        self.bot.tree.add_command(startSpecific_command)

        self.bot.tree.add_command(stop_command)
        self.bot.tree.add_command(stopSpecific_command)

        self.bot.tree.add_command(refresh_cmds_command)

        self.bot.tree.add_command(userdata_command)
        self.bot.tree.add_command(config_command)

        self.bot.tree.add_command(execute_command)

    async def start_live_status_loop(self):
        await self.bot.wait_until_ready()
        channel: TextChannel | None = self.bot.get_channel(self.statusChannelID) if self.statusChannelID else None
        if channel is None:
            print(f"Status channel {self.statusChannelID} not found or not configured.")
            return

        # Build a map of instance name -> existing bot message by scanning recent channel history.
        # We tag each message by matching embed title to instance name so we can resume across restarts.
        existing_messages: dict[str, discord.Message] = {}
        async for msg in channel.history(limit=50):
            if msg.author == self.bot.user and msg.embeds:
                title = msg.embeds[0].title or ""
                for name in self.instance_manager.instances:
                    if name in title and name not in existing_messages:
                        existing_messages[name] = msg

        # For any instance without an existing message, post a fresh embed
        status_messages: dict[str, discord.Message] = {}
        for name, instance in self.instance_manager.instances.items():
            if name in existing_messages:
                status_messages[name] = existing_messages[name]
            else:
                embed = ServerStatusEmbed(instance).build()
                msg = await channel.send(embed=embed)
                status_messages[name] = msg

        # Update loop: Edit each instance embed on every tick
        while not self.bot.is_closed():
            for name, instance in self.instance_manager.instances.items():
                msg = status_messages.get(name)
                if msg:
                    embed = ServerStatusEmbed(instance).build()
                    if instance.status == ServerStatus.SLEEPING:
                        embed.title += " - Stopping"
                    try:
                        await msg.edit(embed=embed)
                    except discord.NotFound:
                        embed = ServerStatusEmbed(instance).build()
                        new_msg = await channel.send(embed=embed)
                        status_messages[name] = new_msg
                    except Exception as e:
                        print(f"[StatusLoop] Failed to update embed for {name}: {e}", flush=True)
            await asyncio.sleep(self.updateInterval)

    async def _start_instance_task(self, instance: ServerInstance):
        try:
            await self.instance_manager.start_instance(instance.name)
            print(f"Server `{instance.name}` is now starting.")
            if self.statusChannelID:
                channel = self.bot.get_channel(self.statusChannelID)
                if channel:
                    pass
        except Exception as e:
            print(f"Error starting server `{instance.name}`: {e}")
            if self.statusChannelID:
                channel = self.bot.get_channel(self.statusChannelID)
                if channel:
                    pass

    def start(self):
        self.bot.run(self.token)