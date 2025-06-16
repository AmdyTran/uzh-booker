#!/usr/bin/env python3
"""
Interactive terminal interface for selecting booking spots and creating configuration.

This script provides a beautiful terminal interface to:
1. Browse available schedules (libraries)
2. Select specific booking spots
3. Generate a new configuration file with selected spots
"""

import asyncio
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table
from rich.text import Text
from rich.progress import Progress, SpinnerColumn, TextColumn

# Add the project root to the path
sys.path.insert(0, str(Path(__file__).parent))

from scheduler.amain import authenticated_session
from scheduler.spot_fetcher import (
    BookingSpot,
    get_all_available_spots,
)
from scheduler.config import BookingDetails

console = Console()


class SpotSelector:
    """Interactive spot selection interface."""

    def __init__(self):
        self.selected_spots: list[BookingSpot] = []
        self.all_spots: dict[str, list[BookingSpot]] = {}

    async def run(self):
        """Main interface loop."""
        console.print(
            Panel.fit(
                "[bold blue]🎯 UZH Booking Spot Selector[/bold blue]\n"
                "Select specific spots to book instead of using ranges",
                title="Welcome",
            )
        )

        try:
            async with authenticated_session() as (client, csrf_token):
                await self._load_spots(client)
                await self._main_menu()

        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            return

    async def _load_spots(self, client):
        """Load all available spots with progress indicator."""
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Loading available spots...", total=None)

            self.all_spots = await get_all_available_spots(client)

            progress.update(task, description="✅ Spots loaded successfully!")
            await asyncio.sleep(0.5)  # Brief pause to show success

    async def _main_menu(self):
        """Main menu interface."""
        while True:
            console.clear()
            self._show_header()

            console.print("\n[bold cyan]📋 Main Menu[/bold cyan]")
            console.print("1. 📚 Browse by library/schedule")
            console.print("2. 🔍 Search spots by name")
            console.print("3. 📝 View selected spots")
            console.print("4. 💾 Generate configuration")
            console.print("5. 🚪 Exit")

            choice = Prompt.ask(
                "\n[bold yellow]Choose an option[/bold yellow]",
                choices=["1", "2", "3", "4", "5"],
                default="1",
            )

            if choice == "1":
                await self._browse_by_schedule()
            elif choice == "2":
                await self._search_spots()
            elif choice == "3":
                await self._view_selected_spots()
            elif choice == "4":
                await self._generate_config()
            elif choice == "5":
                console.print("[green]👋 Goodbye![/green]")
                break

    def _show_header(self):
        """Show header with current selection status."""
        selected_count = len(self.selected_spots)
        total_spots = sum(len(spots) for spots in self.all_spots.values())

        header = Text()
        header.append("🎯 UZH Spot Selector", style="bold blue")
        header.append(f" | Selected: {selected_count} spots", style="green")
        header.append(f" | Available: {total_spots} total", style="dim")

        console.print(Panel(header, title="Status"))

    async def _browse_by_schedule(self):
        """Browse spots by schedule/library."""
        console.clear()
        console.print("[bold cyan]📚 Browse by Library/Schedule[/bold cyan]\n")

        if not self.all_spots:
            console.print("[red]No spots available[/red]")
            Prompt.ask("Press Enter to continue")
            return

        # Show available schedules
        table = Table(title="Available Libraries/Schedules")
        table.add_column("ID", style="cyan", no_wrap=True)
        table.add_column("Library Name", style="green")
        table.add_column("Spots Available", style="yellow")

        schedule_list = []
        for i, (schedule_name, spots) in enumerate(self.all_spots.items(), 1):
            schedule_list.append((schedule_name, spots))
            table.add_row(str(i), schedule_name, str(len(spots)))

        console.print(table)

        # Let user select a schedule
        choice = Prompt.ask(
            f"\n[bold yellow]Select library (1-{len(schedule_list)}) or 'back'[/bold yellow]",
            default="back",
        )

        if choice.lower() == "back":
            return

        try:
            schedule_idx = int(choice) - 1
            if 0 <= schedule_idx < len(schedule_list):
                schedule_name, spots = schedule_list[schedule_idx]
                await self._select_spots_from_list(spots, f"📚 {schedule_name}")
        except ValueError:
            console.print("[red]Invalid selection[/red]")
            await asyncio.sleep(1)

    async def _search_spots(self):
        """Search spots by name."""
        console.clear()
        console.print("[bold cyan]🔍 Search Spots by Name[/bold cyan]\n")

        search_term = Prompt.ask("[bold yellow]Enter search term[/bold yellow]")
        if not search_term:
            return

        # Search through all spots
        matching_spots = []
        search_lower = search_term.lower()

        for spots_list in self.all_spots.values():
            for spot in spots_list:
                if search_lower in spot.name.lower():
                    matching_spots.append(spot)

        if not matching_spots:
            console.print(f"[red]No spots found matching '{search_term}'[/red]")
            Prompt.ask("Press Enter to continue")
            return

        await self._select_spots_from_list(
            matching_spots, f"🔍 Search Results for '{search_term}'"
        )

    async def _select_spots_from_list(self, spots: list[BookingSpot], title: str):
        """Show spots and allow selection."""
        while True:
            console.clear()
            console.print(f"[bold cyan]{title}[/bold cyan]\n")

            # Show spots in a table
            table = Table(title=f"Available Spots ({len(spots)} total)")
            table.add_column("ID", style="cyan", no_wrap=True)
            table.add_column("Spot Name", style="green")
            table.add_column("Library", style="blue")
            table.add_column("Selected", style="yellow")

            for i, spot in enumerate(spots, 1):
                is_selected = "✅" if spot in self.selected_spots else "❌"
                table.add_row(str(i), spot.name, spot.schedule_name, is_selected)

            console.print(table)

            console.print("\n[bold yellow]Commands:[/bold yellow]")
            console.print("• Enter spot ID to toggle selection")
            console.print("• 'all' - select all spots")
            console.print("• 'none' - deselect all spots")
            console.print("• 'back' - return to main menu")

            choice = Prompt.ask(
                "\n[bold yellow]Enter command[/bold yellow]", default="back"
            )

            if choice.lower() == "back":
                break
            elif choice.lower() == "all":
                for spot in spots:
                    if spot not in self.selected_spots:
                        self.selected_spots.append(spot)
                console.print("[green]✅ All spots selected[/green]")
                await asyncio.sleep(1)
            elif choice.lower() == "none":
                for spot in spots:
                    if spot in self.selected_spots:
                        self.selected_spots.remove(spot)
                console.print("[yellow]❌ All spots deselected[/yellow]")
                await asyncio.sleep(1)
            else:
                try:
                    spot_idx = int(choice) - 1
                    if 0 <= spot_idx < len(spots):
                        spot = spots[spot_idx]
                        if spot in self.selected_spots:
                            self.selected_spots.remove(spot)
                            console.print(
                                f"[yellow]❌ Deselected: {spot.name}[/yellow]"
                            )
                        else:
                            self.selected_spots.append(spot)
                            console.print(f"[green]✅ Selected: {spot.name}[/green]")
                        await asyncio.sleep(1)
                    else:
                        console.print("[red]Invalid spot ID[/red]")
                        await asyncio.sleep(1)
                except ValueError:
                    console.print("[red]Invalid input[/red]")
                    await asyncio.sleep(1)

    async def _view_selected_spots(self):
        """View currently selected spots."""
        console.clear()
        console.print("[bold cyan]📝 Selected Spots[/bold cyan]\n")

        if not self.selected_spots:
            console.print("[yellow]No spots selected yet[/yellow]")
            Prompt.ask("Press Enter to continue")
            return

        # Group by schedule
        by_schedule: dict[str, list[BookingSpot]] = {}
        for spot in self.selected_spots:
            if spot.schedule_name not in by_schedule:
                by_schedule[spot.schedule_name] = []
            by_schedule[spot.schedule_name].append(spot)

        # Show grouped results
        for schedule_name, spots in by_schedule.items():
            table = Table(title=f"📚 {schedule_name} ({len(spots)} spots)")
            table.add_column("Spot ID", style="cyan")
            table.add_column("Spot Name", style="green")

            for spot in sorted(spots, key=lambda x: x.name):
                table.add_row(str(spot.id), spot.name)

            console.print(table)
            console.print()

        console.print(
            f"[bold green]Total selected: {len(self.selected_spots)} spots[/bold green]"
        )

        if Confirm.ask("\n[bold yellow]Remove any spots?[/bold yellow]", default=False):
            await self._remove_spots()
        else:
            Prompt.ask("Press Enter to continue")

    async def _remove_spots(self):
        """Remove spots from selection."""
        while True:
            console.clear()
            console.print("[bold cyan]🗑️ Remove Selected Spots[/bold cyan]\n")

            if not self.selected_spots:
                console.print("[yellow]No spots to remove[/yellow]")
                break

            table = Table(title="Currently Selected Spots")
            table.add_column("ID", style="cyan")
            table.add_column("Spot Name", style="green")
            table.add_column("Library", style="blue")

            for i, spot in enumerate(self.selected_spots, 1):
                table.add_row(str(i), spot.name, spot.schedule_name)

            console.print(table)

            choice = Prompt.ask(
                "\n[bold yellow]Enter spot ID to remove or 'done'[/bold yellow]",
                default="done",
            )

            if choice.lower() == "done":
                break

            try:
                spot_idx = int(choice) - 1
                if 0 <= spot_idx < len(self.selected_spots):
                    removed_spot = self.selected_spots.pop(spot_idx)
                    console.print(f"[red]🗑️ Removed: {removed_spot.name}[/red]")
                    await asyncio.sleep(1)
                else:
                    console.print("[red]Invalid spot ID[/red]")
                    await asyncio.sleep(1)
            except ValueError:
                console.print("[red]Invalid input[/red]")
                await asyncio.sleep(1)

    async def _generate_config(self):
        """Generate new configuration file with selected spots."""
        console.clear()
        console.print("[bold cyan]💾 Generate Configuration[/bold cyan]\n")

        if not self.selected_spots:
            console.print("[red]No spots selected! Please select spots first.[/red]")
            Prompt.ask("Press Enter to continue")
            return

        # Show summary
        console.print(f"[green]Selected {len(self.selected_spots)} spots:[/green]")

        # Group by schedule for display
        by_schedule: dict[str, list[BookingSpot]] = {}
        for spot in self.selected_spots:
            if spot.schedule_name not in by_schedule:
                by_schedule[spot.schedule_name] = []
            by_schedule[spot.schedule_name].append(spot)

        for schedule_name, spots in by_schedule.items():
            console.print(f"\n[bold blue]📚 {schedule_name}:[/bold blue]")
            for spot in sorted(spots, key=lambda x: x.name):
                console.print(f"  • {spot.name} (ID: {spot.id})")

        if not Confirm.ask(
            f"\n[bold yellow]Generate config with these {len(self.selected_spots)} spots?[/bold yellow]"
        ):
            return

        # Generate the configuration
        await self._write_config_file()

    async def _write_config_file(self):
        """Write the new configuration file."""
        try:
            # Load current config to preserve other settings
            current_config = BookingDetails()

            # Extract resource IDs
            resource_ids = [spot.id for spot in self.selected_spots]
            resource_ids.sort()  # Sort for consistency

            # Create new config content matching the current structure
            config_content = f'''from diskcache import Cache
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, BaseModel
from pathlib import Path

cache_path = Path(__file__).parent / ".cache"
persistent_cache = Cache(cache_path)


class LoginDetails(BaseSettings):
    model_config = SettingsConfigDict(env_file=Path(__file__).parent / ".env")

    uzh_username: str = Field(alias="UZH_USERNAME")
    uzh_password: str = Field(alias="UZH_PASSWORD")
    uzh_totp_secret: str = Field(alias="UZH_TOTP_SECRET")


class BookingConstants:
    """Centralized constants for booking operations."""

    DEFAULT_TIMEOUT = 15
    CACHE_EXPIRY_HOURS = 6
    MAX_CONCURRENT_BOOKINGS = 50
    TIMEZONE = "Europe/Zurich"

    # HTTP Headers
    USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.3.1 Safari/605.1.15"
    ACCEPT_LANGUAGE = "en-US,en;q=0.9"
    ACCEPT_ENCODING = "gzip, deflate, br"
    CONNECTION = "keep-alive"
    ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"


class BookingDetails(BaseModel):
    base_url: str = "{current_config.base_url}"
    login_page_url: str = base_url + "index.php"
    login_action_url: str = base_url + "index.php"
    tfa_validate_url: str = base_url + "auth/confirm-account.php?action=Confirm"
    owner_id: int = {current_config.owner_id}

    # SELECTED SPOTS CONFIGURATION
    # Generated from spot selector with {len(resource_ids)} spots
    selected_resource_ids: list[int] = {resource_ids}

    # Legacy range settings (not used when selected_resource_ids is provided)
    preferred_range_start: int = {current_config.preferred_range_start}
    preferred_range_end: int = {current_config.preferred_range_end}

    # Booking time settings
    preferred_start_time_hour: int = {current_config.preferred_start_time_hour}
    preferred_start_time_minute: int = {current_config.preferred_start_time_minute}
    preferred_end_time_hour: int = {current_config.preferred_end_time_hour}
    preferred_end_time_minute: int = {current_config.preferred_end_time_minute}

    # Booking attributes
    standard_attribute_values: list[dict[str, str]] = {current_config.standard_attribute_values}

    @property
    def resource_ids_to_book(self) -> list[int]:
        """Get the resource IDs to attempt booking."""
        if self.selected_resource_ids:
            return self.selected_resource_ids
        else:
            # Fallback to range if no specific spots selected
            return list(range(self.preferred_range_start, self.preferred_range_end))
'''

            # Write to config file
            config_path = Path("scheduler/config.py")
            config_path.write_text(config_content)

            console.print(
                f"[bold green]✅ Configuration saved to {config_path}[/bold green]"
            )
            console.print(f"[green]📊 Selected {len(resource_ids)} spots:[/green]")

            # Show selected spots summary
            for i, spot in enumerate(self.selected_spots, 1):
                console.print(
                    f"  {i:2d}. {spot.name} (ID: {spot.id}) - {spot.schedule_name}"
                )

            console.print("\n[bold blue]🎯 Next steps:[/bold blue]")
            console.print("1. Run: [bold cyan]uv run book-async[/bold cyan]")
            console.print("2. The system will now attempt to book these specific spots")
            console.print("3. Check the logs for booking results")

            Prompt.ask("\nPress Enter to continue")

        except Exception as e:
            console.print(f"[red]Error writing config: {e}[/red]")
            Prompt.ask("Press Enter to continue")


async def main_async():
    """Async main entry point."""
    try:
        selector = SpotSelector()
        await selector.run()
    except KeyboardInterrupt:
        console.print("\n[yellow]👋 Cancelled by user[/yellow]")
    except Exception as e:
        console.print(f"\n[red]Error: {e}[/red]")


def main():
    """Synchronous entry point for uv run."""
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
