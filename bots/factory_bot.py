
import discord
from discord.ext import commands
from discord.ui import View, Button
import json
import os
from core.tx_utils import safe_append_tx, get_nonce, get_effective_balance
from dotenv import load_dotenv
from paths import FACTORY_FILE
import math
import time

# --- FactoryBot Constants ---
FACTORY_BASE_UPGRADE_COST = 10000
WORKER_COST = 1000
MACHINE_COST = 2000
MAX_FACTORY_LEVEL = 10
MAX_WORKERS_PER_LEVEL = {lvl: min(2 + (lvl - 1) * 2, 20) for lvl in range(1, MAX_FACTORY_LEVEL + 1)}
MAX_MACHINES_PER_LEVEL = {lvl: min(lvl, 10) for lvl in range(1, MAX_FACTORY_LEVEL + 1)}
BASE_UPGRADE_TIME_MINUTES = 1


def stars_to_efficiency(stars):
    return min(1.0 + 0.5 * math.log2(1 + stars), 5.0)


def fib(n):
    a, b = 10_000, 10_000
    for _ in range(n):
        a, b = b, a + b
    return a


def get_factory_upgrade_cost(current_level):
    if 1 <= current_level < 10:
        return fib(current_level)
    else:
        return None


class FactoryView(View):
    class RollButton(Button):
        def __init__(self, row=None):
            super().__init__(label="🌾 Roll", style=discord.ButtonStyle.green, custom_id="roll", row=row)
        async def callback(self, interaction: discord.Interaction):
            view: FactoryView = self.view
            if interaction.user.id != view.user_id:
                await interaction.response.send_message("This is not your factory!", ephemeral=True)
                return
            # Roll logic: harvest available boilies and update last_harvest
            factory = view.factory_bot.get_user_factory(view.user_id)
            now = time.time()
            prod_rate = view.factory_bot.calculate_production_rate(factory)
            interval = view.factory_bot.HARVEST_INTERVAL
            rolled = view.factory_bot.get_rollable_boilies(factory, now, prod_rate, interval)
            if rolled <= 0:
                await interaction.response.send_message("⏳ No boilies ready to roll yet. Please wait!", ephemeral=True)
                return

            tx = {
                "type": "tip",
                "user_id": str(view.factory_bot.FACTORYBOT_ID),
                "username": "Factory Bot",
                "to": str(view.user_id),
                "to_username": str(interaction.user),
                "amount": rolled,
                "reason": "factory roll",
                "nonce": get_nonce(view.factory_bot.FACTORYBOT_ID)
            }

            success = safe_append_tx(tx)
            if not success:
                await interaction.response.send_message(
                    "❌ Failed to record transaction (possible duplicate).", ephemeral=True
                )
                return

            factory["boilies"] += rolled
            factory["last_harvest"] = now
            view.factory_bot.update_user_factory(view.user_id, factory)

            await interaction.response.send_message(
                f"🌾 You rolled **{rolled}** fresh BOILIES! They've been sent to your wallet.",
                ephemeral=True
            )

    class RefreshButton(discord.ui.Button):
        def __init__(self, user_id, factory_bot, row=0):
            super().__init__(label="🔄 Refresh", style=discord.ButtonStyle.blurple, custom_id="refresh", row=row)
            self.user_id = user_id
            self.factory_bot = factory_bot

        async def callback(self, interaction: discord.Interaction):
            factory = self.factory_bot.get_user_factory(self.user_id)
            embed = self.factory_bot.create_factory_embed(factory)
            await interaction.response.edit_message(embed=embed, view=self.view)

    class BuyWorkerButton(Button):
        def __init__(self, row=None):
            super().__init__(label=f"👷 Hire Worker ({WORKER_COST} BOILIES)", style=discord.ButtonStyle.primary, custom_id="buy_worker", row=row)
        async def callback(self, interaction: discord.Interaction):
            view: FactoryView = self.view
            if interaction.user.id != view.user_id:
                await interaction.response.send_message("This is not your factory!", ephemeral=True)
                return
            factory = view.factory_bot.get_user_factory(view.user_id)
            # Check max workers for current factory level
            max_workers = MAX_WORKERS_PER_LEVEL.get(factory["factory_level"], 1)
            if len(factory.get("workers", [])) >= max_workers:
                await interaction.response.send_message(
                    f"❌ You already have the maximum number of workers ({max_workers}) for your factory level.",
                    ephemeral=True
                )
                return
            # Check balance
            balance = get_effective_balance(str(view.user_id))
            if balance < WORKER_COST:
                await interaction.response.send_message("❌ Not enough BOILIES to buy a worker.", ephemeral=True)
                return
            tx = {
                "type": "tip",
                "user_id": str(view.user_id),
                "username": str(interaction.user),
                "to": str(view.factory_bot.FACTORYBOT_ID),
                "to_username": "Factory Bot",
                "amount": WORKER_COST,
                "reason": "buy worker",
                "nonce": get_nonce(str(view.user_id))
            }
            success = safe_append_tx(tx)
            if not success:
                await interaction.response.send_message("❌ Still processing the previous action. Please try again.", ephemeral=True)
                return
            # Add new worker
            factory.setdefault("workers", []).append({"stars": 1, "upgrade_ready_time": None})
            view.factory_bot.update_user_factory(view.user_id, factory)
            await interaction.response.send_message("👷 Worker hired and ready to produce more BOILIES!", ephemeral=True)

    class BuyMachineButton(Button):
        def __init__(self, row=None):
            super().__init__(label=f"🛠️ Buy Machine ({MACHINE_COST} BOILIES)", style=discord.ButtonStyle.primary, custom_id="buy_machine", row=row)
        async def callback(self, interaction: discord.Interaction):
            view: FactoryView = self.view
            if interaction.user.id != view.user_id:
                await interaction.response.send_message("This is not your factory!", ephemeral=True)
                return
            factory = view.factory_bot.get_user_factory(view.user_id)
            now = time.time()
            # Check max machines for current factory level
            max_machines = MAX_MACHINES_PER_LEVEL.get(factory["factory_level"], 1)
            if len(factory.get("machines", [])) >= max_machines:
                await interaction.response.send_message(
                    f"❌ You already have the maximum number of machines ({max_machines}) for your factory level.",
                    ephemeral=True
                )
                return
            # Check balance
            balance = get_effective_balance(str(view.user_id))
            if balance < MACHINE_COST:
                await interaction.response.send_message("❌ Not enough BOILIES to buy a machine.", ephemeral=True)
                return
            tx = {
                "type": "tip",
                "user_id": str(view.user_id),
                "username": str(interaction.user),
                "to": str(view.factory_bot.FACTORYBOT_ID),
                "to_username": "Factory Bot",
                "amount": MACHINE_COST,
                "reason": "buy machine",
                "nonce": get_nonce(str(view.user_id))
            }
            success = safe_append_tx(tx)
            if not success:
                await interaction.response.send_message("❌ Still processing the previous action. Please try again.", ephemeral=True)
                return
            # Add new machine
            factory.setdefault("machines", []).append({"stars": 1, "upgrade_ready_time": None})
            view.factory_bot.update_user_factory(view.user_id, factory)
            await interaction.response.send_message("🛠️ New machine installed! Your production is more efficient.", ephemeral=True)

    class UpgradeWorkerButton(Button):
        def __init__(self, row=None):
            super().__init__(label="⭐ Upgrade Worker", style=discord.ButtonStyle.gray, custom_id="upgrade_worker", row=row)
        async def callback(self, interaction: discord.Interaction):
            view: FactoryView = self.view
            if interaction.user.id != view.user_id:
                await interaction.response.send_message("This is not your factory!", ephemeral=True)
                return
            # Show worker selection view for upgrade
            upgrade_view = SelectWorkerView(view.user_id, view.factory_bot)
            await interaction.response.send_message(
                "Select a worker to upgrade:",
                view=upgrade_view,
                ephemeral=True
            )

    class UpgradeMachineButton(Button):
        def __init__(self, row=None):
            super().__init__(label="⚙️ Upgrade Machine", style=discord.ButtonStyle.gray, custom_id="upgrade_machine", row=row)
        async def callback(self, interaction: discord.Interaction):
            view: FactoryView = self.view
            if interaction.user.id != view.user_id:
                await interaction.response.send_message("This is not your factory!", ephemeral=True)
                return
            # Show machine selection view for upgrade
            upgrade_view = SelectMachineView(view.user_id, view.factory_bot)
            await interaction.response.send_message(
                "Select a machine to upgrade:",
                view=upgrade_view,
                ephemeral=True
            )

    def __init__(self, user_id, factory_bot, requester=None):
        super().__init__(timeout=None)
        self.user_id = int(user_id)
        self.factory_bot = factory_bot
        self.factory_bot.data = self.factory_bot.load_data()
        import discord.utils
        # Only add buttons if not already present and if the current user is the one viewing (via requester)
        if discord.utils.get(self.children, custom_id="roll") is None:
            # Add if requester is the owner OR no requester is provided
            if requester is None or requester.id == self.user_id:
                self.add_item(self.RollButton(row=0))
                self.add_item(self.RefreshButton(self.user_id, self.factory_bot, row=0))
                self.add_item(self.BuyWorkerButton(row=1))
                self.add_item(self.BuyMachineButton(row=2))
                self.add_item(self.UpgradeWorkerButton(row=1))
                self.add_item(self.UpgradeMachineButton(row=2))
                factory = self.factory_bot.get_user_factory(self.user_id)
                current_level = factory["factory_level"]
                # upgrade_cost = int(FACTORY_BASE_UPGRADE_COST * (1.5 ** (current_level - 1)))
                upgrade_cost = get_factory_upgrade_cost(current_level)
                self.add_item(self.UpgradeFactoryButton(current_level, upgrade_cost, row=3))

    class UpgradeFactoryButton(Button):
        def __init__(self, current_level, upgrade_cost, row=None):
            super().__init__(
                label=f"🏗️ Upgrade Factory (Lvl {current_level} → {current_level + 1}, {upgrade_cost} BOILIES)",
                style=discord.ButtonStyle.blurple,
                custom_id="upgrade_factory",
                row=row
            )
            self.upgrade_cost = upgrade_cost

        async def callback(self, interaction: discord.Interaction):
            try:
                view: FactoryView = self.view
                if interaction.user.id != view.user_id:
                    await interaction.response.send_message("This is not your factory!", ephemeral=True)
                    return

                factory = view.factory_bot.get_user_factory(view.user_id)
                now = time.time()
                upgrade_time = factory.get("upgrade_ready_time") or 0
                print(f"Remaining upgrade time for factory: {upgrade_time}.")
                if upgrade_time > now:
                    remaining = int(upgrade_time - now)
                    hours = remaining // 3600
                    mins = (remaining % 3600) // 60
                    await interaction.response.send_message(
                        f"⏳ Factory upgrade already in progress. Ready in {hours}h {mins}m.",
                        ephemeral=True
                    )
                    return

                if factory["factory_level"] >= MAX_FACTORY_LEVEL:
                    await interaction.response.send_message("🏗️ Your factory is already max level!", ephemeral=True)
                    return

                balance = get_effective_balance(str(view.user_id))
                if balance < self.upgrade_cost:
                    await interaction.response.send_message("❌ Not enough BOILIES to upgrade your factory.", ephemeral=True)
                    return

                tx = {
                    "type": "tip",
                    "user_id": str(view.user_id),
                    "username": str(interaction.user),
                    "to": str(view.factory_bot.FACTORYBOT_ID),
                    "to_username": "Factory Bot",
                    "amount": self.upgrade_cost,
                    "reason": "upgrade factory",
                    "nonce": get_nonce(str(view.user_id))
                }
                success = safe_append_tx(tx)
                if not success:
                    await interaction.response.send_message("❌ Still processing the previous action. Please try again.", ephemeral=True)
                    return

                # Exponential upgrade duration: BASE_UPGRADE_TIME_MINUTES * (2 ** level)
                level = factory["factory_level"]
                duration_minutes = BASE_UPGRADE_TIME_MINUTES * (2 ** level)
                factory["upgrade_ready_time"] = time.time() + duration_minutes * 60
                view.factory_bot.update_user_factory(view.user_id, factory)
                await interaction.response.send_message(
                    f"🏗️ Factory upgrade started! It will complete in {int(duration_minutes // 60)}h {int(duration_minutes % 60)}m.",
                    ephemeral=True
                )

            except Exception as e:
                import traceback
                print("❌ Error in UpgradeFactoryButton.callback:", e)
                traceback.print_exc()
                try:
                    await interaction.response.send_message("❌ Internal error during factory upgrade.", ephemeral=True)
                except discord.errors.InteractionResponded:
                    pass


class SelectWorkerView(discord.ui.View):
    def __init__(self, user_id, factory_bot):
        super().__init__(timeout=60)
        self.user_id = int(user_id)
        self.factory_bot = factory_bot
        self.factory_bot.data = self.factory_bot.load_data()
        self.factory = factory_bot.get_user_factory(self.user_id)
        self.balance = get_effective_balance(str(self.user_id))

        for idx, worker in enumerate(self.factory.get("workers", [])):
            stars = worker.get("stars", 0)

            # Max-Level reached?
            if stars >= 5:
                label = f"👷 Worker {idx+1}: Fully Upgraded ({stars}⭐)"
                self.add_item(SelectWorkerButton(idx, label, discord.ButtonStyle.gray, 0, disabled=True))
                continue

            cost = int(WORKER_COST * (2 ** stars))
            upgrade_ready_time = worker.get("upgrade_ready_time")

            # Upgrade active?
            disabled = upgrade_ready_time is not None and time.time() < upgrade_ready_time

            if disabled:
                label = f"👷 Worker {idx+1}: Upgrading… ({stars}⭐ → {stars+1}⭐)"
            else:
                label = f"👷 Upgrade Worker to {stars + 1}⭐ – {cost} Boilies"

            style = discord.ButtonStyle.gray if disabled else (
                discord.ButtonStyle.green if self.balance >= cost else discord.ButtonStyle.gray
            )

            self.add_item(SelectWorkerButton(idx, label, style, cost, disabled=disabled))


class SelectWorkerButton(discord.ui.Button):
    def __init__(self, worker_index, label, style, cost, disabled=False):
        super().__init__(label=label, style=style, custom_id=f"upgrade_worker_{worker_index}", disabled=disabled)
        self.worker_index = worker_index
        self.cost = cost

    async def callback(self, interaction: discord.Interaction):
        try:
            view: SelectWorkerView = self.view
            if interaction.user.id != view.user_id:
                await interaction.response.send_message("This is not your factory!", ephemeral=True)
                return

            factory = view.factory_bot.get_user_factory(view.user_id)
            now = time.time()
            try:
                worker = factory["workers"][self.worker_index]
            except IndexError:
                await interaction.response.send_message("❌ Worker not found.", ephemeral=True)
                return

            upgrade_ready_time = worker.get("upgrade_ready_time")
            if upgrade_ready_time is not None and now < upgrade_ready_time:
                remaining = int(upgrade_ready_time - now)
                hours = remaining // 3600
                mins = (remaining % 3600) // 60
                await interaction.response.send_message(
                    f"Upgrade in progress. Ready in {hours}h {mins}m.", ephemeral=True
                )
                return

            factory_level = factory.get("factory_level", 1)
            max_stars = min(factory_level + 1, 5)
            current_stars = worker.get("stars", 0)
            if current_stars + 1 > max_stars:
                await interaction.response.send_message(
                    f"❌ Workers can only be upgraded up to {max_stars}⭐ with your current factory level.",
                    ephemeral=True
                )
                return

            cost = int(WORKER_COST * (2 ** current_stars))
            balance = get_effective_balance(str(view.user_id))
            if balance < cost:
                await interaction.response.send_message("❌ Not enough BOILIES to upgrade this worker.", ephemeral=True)
                return

            tx = {
                "type": "tip",
                "user_id": str(view.user_id),
                "username": str(interaction.user),
                "to": str(view.factory_bot.FACTORYBOT_ID),
                "to_username": "Factory Bot",
                "amount": cost,
                "reason": "upgrade worker",
                "nonce": get_nonce(str(view.user_id))
            }
            success = safe_append_tx(tx)
            if not success:
                await interaction.response.send_message("❌ Still processing the previous action. Please try again.", ephemeral=True)
                return

            duration_minutes = BASE_UPGRADE_TIME_MINUTES * (1.5 ** (current_stars + 1))
            worker["upgrade_ready_time"] = now + duration_minutes * 60
            view.factory_bot.update_user_factory(view.user_id, factory)
            hours = int(duration_minutes // 60)
            mins = int(duration_minutes % 60)
            msg = f"⏳ Upgrade started: This worker will reach {current_stars + 1}⭐ in {hours}h {mins}m."

            if interaction.response.is_done():
                await interaction.followup.send(message=msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)

        except Exception as e:
            import traceback
            print("❌ Error in SelectWorkerButton.callback:", e)
            traceback.print_exc()
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ Internal error during worker upgrade.", ephemeral=True)
            else:
                await interaction.followup.send("❌ Internal error during worker upgrade.", ephemeral=True)


class SelectMachineView(discord.ui.View):
    def __init__(self, user_id, factory_bot):
        super().__init__(timeout=60)
        self.user_id = int(user_id)
        self.factory_bot = factory_bot
        self.factory_bot.data = self.factory_bot.load_data()
        self.factory = factory_bot.get_user_factory(self.user_id)
        self.balance = get_effective_balance(str(self.user_id))
        for idx, machine in enumerate(self.factory.get("machines", [])):
            stars = machine.get("stars", 0)
            # Show a disabled button for maxed machines
            if stars > 4:
                label = f"⚙️ Machine {idx+1}: Fully Upgraded ({stars}⭐)"
                self.add_item(SelectMachineButton(idx, label, discord.ButtonStyle.gray, 0, disabled=True))
                continue
            cost = int(MACHINE_COST * (2 ** stars))
            disabled = machine.get("upgrade_ready_time", 0) and time.time() < machine.get("upgrade_ready_time", 0)
            # For in-progress upgrades, show an upgrading label, else normal upgrade label
            if disabled and stars < 5:
                label = f"⚙️ Machine {idx+1}: Upgrading… ({stars}⭐ → {stars+1}⭐)"
            else:
                label = f"⚙️ Upgrade Machine to {stars + 1}⭐ – {cost} Boilies"
            style = discord.ButtonStyle.gray if disabled else (
                discord.ButtonStyle.green if self.balance >= cost else discord.ButtonStyle.gray
            )
            self.add_item(SelectMachineButton(idx, label, style, cost, disabled=disabled))


class SelectMachineButton(discord.ui.Button):
    def __init__(self, machine_index, label, style, cost, disabled=False):
        super().__init__(label=label, style=style, custom_id=f"upgrade_machine_{machine_index}", disabled=disabled)
        self.machine_index = machine_index
        self.cost = cost

    async def callback(self, interaction: discord.Interaction):
        view: SelectMachineView = self.view
        if interaction.user.id != view.user_id:
            await interaction.response.send_message("This is not your factory!", ephemeral=True)
            return

        factory = view.factory_bot.get_user_factory(view.user_id)
        now = time.time()
        try:
            machine = factory["machines"][self.machine_index]
        except IndexError:
            await interaction.response.send_message("❌ Machine not found.", ephemeral=True)
            return

        upgrade_ready_time = machine.get("upgrade_ready_time")
        if upgrade_ready_time is not None and now < upgrade_ready_time:
            remaining = int(upgrade_ready_time - now)
            hours = remaining // 3600
            mins = (remaining % 3600) // 60
            await interaction.response.send_message(
                f"Upgrade in progress. Ready in {hours}h {mins}m.", ephemeral=True
            )
            return

        current_stars = machine.get("stars", 0)
        factory_level = factory.get("factory_level", 1)
        max_level = min(factory_level + 1, 5)
        if current_stars + 1 > max_level:
            await interaction.response.send_message(f"❌ Machines can only be upgraded to {max_level} stars with your current factory level.", ephemeral=True)
            return

        if current_stars >= 5:
            await interaction.response.send_message("❌ This machine is already max level.", ephemeral=True)
            return

        cost = int(MACHINE_COST * (2 ** current_stars))
        balance = get_effective_balance(str(view.user_id))
        if balance < cost:
            await interaction.response.send_message("❌ Not enough BOILIES to upgrade this machine.", ephemeral=True)
            return

        tx = {
            "type": "tip",
            "user_id": str(view.user_id),
            "username": str(interaction.user),
            "to": str(view.factory_bot.FACTORYBOT_ID),
            "to_username": "Factory Bot",
            "amount": cost,
            "reason": "upgrade machine",
            "nonce": get_nonce(str(view.user_id))
        }

        success = safe_append_tx(tx)
        if not success:
            await interaction.response.send_message("❌ Failed to record transaction.", ephemeral=True)
            return

        duration_minutes = BASE_UPGRADE_TIME_MINUTES * (1.5 ** (current_stars + 1))
        machine["upgrade_ready_time"] = now + duration_minutes * 60
        view.factory_bot.update_user_factory(view.user_id, factory)
        hours = int(duration_minutes // 60)
        mins = int(duration_minutes % 60)
        await interaction.response.send_message(
            f"⏳ Machine upgrade to {current_stars + 1}⭐ started! Time until completion: {hours}h {mins}m",
            ephemeral=True
        )


class FactoryBot:
    DATA_FILE = FACTORY_FILE
    # DEFAULT_PROD = 5  # base Boilies/hour for factory level 1

    def __init__(self):
        load_dotenv()
        self.FACTORYBOT_ID = os.getenv("FACTORYBOT_ID")
        self.FACTORYBOT_CHANNELS = [int(x.strip()) for x in os.getenv("FACTORYBOT_CHANNEL_IDS", "").split(",") if x.strip()]
        self.DEFAULT_PROD = 10  # base Boilies/hour for factory level 1
        self.HARVEST_INTERVAL = 60  # seconds per harvest unit, adjustable for testing
        self.treasury = self.FACTORYBOT_ID
        intents = discord.Intents.all()
        self.bot = commands.Bot(command_prefix="!", intents=intents)
        self.data = self.load_data()
        self.register_commands()
        self._stop_event = None

    def load_data(self):
        if not os.path.exists(self.DATA_FILE):
            return {}
        with open(self.DATA_FILE, "r") as f:
            return json.load(f)

    def save_data(self):
        with open(self.DATA_FILE, "w") as f:
            json.dump(self.data, f, indent=2)

    def get_rollable_boilies(self, factory, now, prod_rate, interval):
        elapsed = int((now - factory["last_harvest"]) // interval)
        return round(prod_rate * elapsed * interval / 3600)

    def get_user_factory(self, user_id):
        user_id = str(user_id)
        factory = self.data.get(user_id)
        # Add missing upgrade_ready_time fields and migrate efficiency→stars for machines
        changed = False
        if factory:
            if "upgrade_ready_time" not in factory:
                factory["upgrade_ready_time"] = None
                changed = True
            if "workers" in factory:
                for w in factory["workers"]:
                    if "upgrade_ready_time" not in w:
                        w["upgrade_ready_time"] = 0
                        changed = True
            if "machines" in factory:
                for m in factory["machines"]:
                    if "upgrade_ready_time" not in m:
                        m["upgrade_ready_time"] = 0
                        changed = True
            if changed:
                self.update_user_factory(user_id, factory)
        return factory

    def update_user_factory(self, user_id, factory):
        self.data[str(user_id)] = factory
        self.save_data()

    def calculate_production_rate(self, factory):
        base_rate = factory["factory_level"] * self.DEFAULT_PROD
        worker_bonus = sum(w.get("stars", 0) * 2 for w in factory.get("workers", []))
        base_production = base_rate + worker_bonus
        machine_stars = sum(m.get("stars", 0) for m in factory.get("machines", []))
        machine_multiplier = 1.0 + 0.5 * math.log2(1 + machine_stars)
        machine_multiplier = min(machine_multiplier, 5.0)
        return int(base_production * machine_multiplier)

    def register_commands(self):
        @self.bot.tree.command(name="factory", description="Show your Boilie Factory")
        async def factory_command(interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True)
            # Ensure latest data is loaded before showing the factory
            self.data = self.load_data()
            await self.show_factory_overview(interaction)

    async def show_factory_overview(self, interaction: discord.Interaction, factory=None):
        print(f"✅ show_factory_overview called for user: {interaction.user.id}")
        try:
            user_id = interaction.user.id
            if not factory:
                self.load_data()
                factory = self.get_user_factory(str(user_id))

            if not factory:
                print("📭 No factory found, sending build prompt")
                view = discord.ui.View()

                class BuildFactoryButton(discord.ui.Button):
                    def __init__(self, factory_bot):
                        super().__init__(label="🏭 Build Factory (10 000 Boilies)", style=discord.ButtonStyle.success)
                        self.factory_bot = factory_bot

                    async def callback(self, interaction: discord.Interaction):
                        from core.tx_utils import get_effective_balance, get_nonce, safe_append_tx
                        effective = get_effective_balance(str(interaction.user.id))
                        if effective < 10_000:
                            await interaction.response.send_message("❌ Not enough BOILIES to build a factory.", ephemeral=True)
                            return
                        tx = {
                            "type": "tip",
                            "user_id": str(interaction.user.id),
                            "username": str(interaction.user),
                            "to": self.factory_bot.FACTORYBOT_ID,
                            "to_username": "Factory System",
                            "amount": 10_000,
                            "reason": "Initial Factory Build",
                            "nonce": get_nonce(str(interaction.user.id))
                        }
                        if not safe_append_tx(tx):
                            await interaction.response.send_message("⚠️ Transaction already pending. Please wait.", ephemeral=True)
                            return
                        new_factory = {
                            "factory_level": 1,
                            "boilies": 0,
                            "last_harvest": time.time(),
                            "workers": [],
                            "machines": [],
                            "upgrade_slots": [],
                            "upgrade_ready_time": None
                        }
                        # Patch: set new_factory_user_id, update, fetch, and show overview
                        new_factory_user_id = str(interaction.user.id)
                        self.factory_bot.update_user_factory(new_factory_user_id, new_factory)
                        new_factory_obj = self.factory_bot.get_user_factory(new_factory_user_id)
                        await self.factory_bot.show_factory_overview(interaction, factory=new_factory_obj)

                view.add_item(BuildFactoryButton(self))

                # Send the message using followup to avoid InteractionResponded error
                await interaction.followup.send("You don't own a factory yet. Would you like to build one?", view=view, ephemeral=True)
                return

            self.load_data()
            embed = self.create_factory_embed(factory)
            # Ensure user_id is int
            user_id = int(user_id)
            # view = FactoryView(user_id, self)
            view = FactoryView(user_id, self, requester=interaction.user)
            # Patch: check is_done before sending
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

        except Exception as e:
            print(f"❌ Error in show_factory_overview: {e}")
            import traceback
            traceback.print_exc()
            try:
                await interaction.followup.send("❌ Failed to display your factory.", ephemeral=True)
            except discord.errors.InteractionResponded:
                pass  # Already responded elsewhere

    def create_factory_embed(self, factory):
        """
        Returns a discord.Embed with detailed factory status, including:
        - Worker/machine counts with star/efficiency breakdowns and upgrade timers
        - Production bonus breakdowns
        - Upgrade timers
        """
        import discord
        import math
        from collections import Counter
        user_name = "Your"
        embed = discord.Embed(title=f"🏭 {user_name} Boilie Factory")
        now = time.time()
        default_prod = self.DEFAULT_PROD
        harvest_interval = self.HARVEST_INTERVAL

        # --- Factory Upgrade Status ---
        upgrade_time = factory.get("upgrade_ready_time")
        if upgrade_time is not None and now < upgrade_time:
            remaining = int(upgrade_time - now)
            hours = remaining // 3600
            minutes = (remaining % 3600) // 60
            upgrade_status = f"⏳ Upgrade ready in {hours}h {minutes}m"
        elif upgrade_time and now >= upgrade_time:
            upgrade_status = "✅ Upgrade complete! Awaiting collection."
        else:
            upgrade_status = "✅ No upgrade in progress"
        embed.add_field(name="Factory Upgrade Status", value=upgrade_status, inline=False)

        # --- Level & Boilies ---
        embed.add_field(name="Level", value=factory["factory_level"], inline=True)
        embed.add_field(name="Boilies collected", value=factory["boilies"], inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)

        # --- Workers ---
        workers = factory.get("workers", [])
        embed.add_field(name="Workers", value=f"{len(workers)} hired", inline=True)
        upgrading_workers = []
        for idx, w in enumerate(workers):
            uet = w.get("upgrade_ready_time")
            stars = w.get("stars", 0)
            if uet and now < uet:
                upgrading_workers.append((idx, stars, uet))

        # --- Machines ---
        machines = factory.get("machines", [])
        embed.add_field(name="Machines", value=f"{len(machines)} installed", inline=True)
        upgrading_machines = []
        for idx, m in enumerate(machines):
            uet = m.get("upgrade_ready_time")
            stars = m.get("stars", 0)
            if uet and now < uet:
                upgrading_machines.append((idx, stars, uet))


        # --- Production Breakdown ---
        # Calculate production rate inline instead of using self.calculate_production_rate
        worker_bonus = 0
        worker_star_counts = Counter(w.get("stars", 0) for w in workers)
        for s, n in worker_star_counts.items():
            worker_bonus += n * s * 2
        worker_parts = [f"{n}×{s}⭐" for s, n in sorted(worker_star_counts.items(), reverse=True)]
        # Machines breakdown: count by stars
        star_counts = Counter(m.get("stars", 0) for m in machines)
        multi_parts = [f"{count}x{stars}⭐" for stars, count in sorted(star_counts.items(), reverse=True)]
        base_rate = factory["factory_level"] * default_prod
        machine_stars = sum(m.get("stars", 0) for m in machines)
        machine_multiplier = 1.0 + 0.5 * math.log2(1 + machine_stars)
        machine_multiplier = min(machine_multiplier, 5.0)
        prod_rate = int((base_rate + worker_bonus) * machine_multiplier)
        rolled = self.get_rollable_boilies(factory, now, prod_rate, harvest_interval)
        breakdown_lines = [
            f"Base rate: **{base_rate}** (Factory Level {factory['factory_level']} × {default_prod})",
            f"Worker bonus: **+{worker_bonus}** ({', '.join(worker_parts)})",
            f"Machine multiplier: **×{machine_multiplier:.2f}** ({', '.join(multi_parts)})" if multi_parts else f"Machine multiplier: **×{machine_multiplier:.2f}**",
            f"Final rate: **{prod_rate} Boilies/hour**",
        ]
        embed.add_field(name="Production Breakdown", value="\n".join(breakdown_lines), inline=False)
        embed.add_field(name="Boilies", value=f"{rolled} ready to roll")

        # --- Upgrade Timers ---
        for idx, stars, uet in upgrading_workers:
            remaining = int(uet - now)
            hours = remaining // 3600
            minutes = (remaining % 3600) // 60
            embed.add_field(name=f"Worker #{idx+1} Upgrade", value=f"⏳ {stars}→{stars+1}⭐ (ready in {hours}h {minutes}m)", inline=False)
        for idx, stars, uet in upgrading_machines:
            next_stars = stars + 1
            remaining = int(uet - now)
            hours = remaining // 3600
            minutes = (remaining % 3600) // 60
            embed.add_field(name=f"Machine #{idx+1} Upgrade", value=f"⏳ {stars}→{next_stars}⭐ (ready in {hours}h {minutes}m)", inline=False)

        return embed


def create_factory_bot():
    return FactoryBot()


def run_bot(stop_event=None):
    import asyncio
    import os

    BotClass = create_factory_bot()
    bot = BotClass

    @bot.bot.event
    async def on_ready():
        await bot.bot.tree.sync()
        print(f"✅ Slash commands synced as {bot.bot.user}")

    async def runner():
        async def shutdown_watcher():
            while not stop_event.is_set():
                await asyncio.sleep(1)
            print("🔻 Shutdown signal received. Closing Factory Bot...")
            await bot.bot.close()

        try:
            if stop_event:
                asyncio.create_task(shutdown_watcher())
            await bot.bot.start(os.getenv("DISCORD_TOKEN_FACTORY"))
        except Exception as e:
            print(f"❌ Factory Bot runner error: {e}")
        finally:
            await bot.bot.close()
            await asyncio.sleep(0.1)

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(runner())
    finally:
        loop.close()
        print("🔻 Factory Bot has shut down.")
