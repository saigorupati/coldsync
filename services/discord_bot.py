import httpx
from datetime import datetime, timezone


class DiscordService:
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url
        self.http = httpx.AsyncClient(timeout=10)

    async def _send_embed(self, embed: dict):
        try:
            await self.http.post(self.webhook_url, json={"embeds": [embed]})
        except Exception:
            pass

    async def _send(self, content: str):
        try:
            await self.http.post(self.webhook_url, json={"content": content})
        except Exception:
            pass

    async def send_trade_alert(self, trade: dict):
        trade_type = trade.get("type", "")
        status = trade.get("status", "")
        note = trade.get("note", "")
        question = trade.get("question", "")[:80]
        price = trade.get("intended_price", 0)
        count = trade.get("count", 0)
        cost = trade.get("cost_usd", 0)
        city_date = trade.get("city_date", "")

        if "no_buy" in trade_type or "no_limit" in trade_type:
            tier = trade_type.split("_")[-1]
            title = f"No Buy — Tier {tier}"
            color = {"A": 0xEF4444, "B": 0xF97316, "C": 0xEAB308, "D": 0x3B82F6}.get(tier, 0x6B7280)
        elif "exit" in trade_type:
            title = f"Exit — {trade_type}"
            color = 0xF59E0B
        else:
            title = f"{trade_type}"
            color = 0x6B7280

        if status == "matched":
            status_text = "Filled"
        elif status == "resting":
            status_text = "Resting on book"
        elif status == "error":
            status_text = "Error"
        elif status == "dry_run":
            status_text = "Dry Run"
        else:
            status_text = status

        fields = [
            {"name": "Market", "value": f"`{question}`", "inline": False},
        ]

        if city_date:
            parts = city_date.split("|") if "|" in city_date else [city_date, ""]
            fields.append({"name": "City", "value": parts[0], "inline": True})
            if parts[1]:
                fields.append({"name": "Date", "value": parts[1], "inline": True})

        fields.append({"name": "Price", "value": f"{price * 100:.1f}c", "inline": True})

        if count > 0:
            fields.append({"name": "Contracts", "value": str(count), "inline": True})
            fields.append({"name": "Cost", "value": f"${cost:.2f}", "inline": True})

        fields.append({"name": "Status", "value": status_text, "inline": True})

        if note:
            fields.append({"name": "Note", "value": note, "inline": False})

        embed = {
            "title": title,
            "color": color,
            "fields": fields,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "footer": {"text": "ColdSync"},
        }
        await self._send_embed(embed)

    async def send_exit_alert(self, ticker: str, stage: int, contracts_sold: int,
                               sell_price: float, entry_price: float, pnl: float, reason: str):
        stage_labels = {
            1: "Cut Some (20%)",
            2: "Cut Heavy (30%)",
            3: "Full Exit (40%)",
            4: "YES Flip Stop-Loss",
        }
        color = 0xF59E0B if stage < 3 else 0xEF4444 if stage == 3 else 0xA855F7

        embed = {
            "title": f"Exit Stage {stage}",
            "color": color,
            "fields": [
                {"name": "Ticker", "value": f"`{ticker}`", "inline": False},
                {"name": "Stage", "value": stage_labels.get(stage, str(stage)), "inline": True},
                {"name": "Sold", "value": f"{contracts_sold} contracts", "inline": True},
                {"name": "Entry", "value": f"{entry_price * 100:.1f}c", "inline": True},
                {"name": "Exit", "value": f"{sell_price * 100:.1f}c", "inline": True},
                {"name": "P&L", "value": f"**${pnl:+.2f}**", "inline": True},
                {"name": "Reason", "value": reason, "inline": False},
            ],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "footer": {"text": "ColdSync"},
        }
        await self._send_embed(embed)

    async def send_resolution_alert(self, pos: dict, outcome: str, payout: float, pnl: float):
        is_win = pnl >= 0
        title = f"{'Win' if is_win else 'Loss'} — {outcome}"
        color = 0x22C55E if is_win else 0xEF4444
        question = pos.get("question", "")[:80]
        cost = float(pos.get("no_cost", 0))
        city_date = pos.get("city_date", "")
        no_contracts = int(pos.get("no_contracts", 0))

        fields = [
            {"name": "Market", "value": f"`{question}`", "inline": False},
        ]

        if city_date:
            parts = city_date.split("|") if "|" in city_date else [city_date, ""]
            fields.append({"name": "City", "value": parts[0], "inline": True})
            if parts[1]:
                fields.append({"name": "Date", "value": parts[1], "inline": True})

        fields.extend([
            {"name": "Outcome", "value": f"**{outcome}**", "inline": True},
            {"name": "NO Contracts", "value": str(no_contracts), "inline": True},
            {"name": "Cost", "value": f"${cost:.2f}", "inline": True},
            {"name": "Payout", "value": f"${payout:.2f}", "inline": True},
            {"name": "P&L", "value": f"**${pnl:+.2f}**", "inline": True},
        ])

        embed = {
            "title": title,
            "color": color,
            "fields": fields,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "footer": {"text": "ColdSync"},
        }
        await self._send_embed(embed)

    async def send_yes_flip_alert(self, ticker: str, yes_contracts: int,
                                    yes_price: float, no_loss: float,
                                    spend: float, city_date: str):
        fields = [
            {"name": "Ticker", "value": f"`{ticker}`", "inline": False},
            {"name": "YES Contracts", "value": str(yes_contracts), "inline": True},
            {"name": "YES Price", "value": f"{yes_price * 100:.1f}c", "inline": True},
            {"name": "Spend", "value": f"${spend:.2f}", "inline": True},
            {"name": "NO Loss", "value": f"${no_loss:.2f}", "inline": True},
            {"name": "Potential Payout", "value": f"${yes_contracts:.2f}", "inline": True},
        ]
        if city_date:
            parts = city_date.split("|") if "|" in city_date else [city_date, ""]
            fields.insert(1, {"name": "City", "value": parts[0], "inline": True})

        embed = {
            "title": "Stage 4: YES Flip",
            "color": 0xA855F7,  # purple
            "fields": fields,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "footer": {"text": "ColdSync"},
        }
        await self._send_embed(embed)

    async def send_yes_resolution_alert(self, ypos: dict, outcome: str, payout: float, pnl: float):
        is_win = pnl >= 0
        title = f"YES Flip {'Win' if is_win else 'Loss'} — {outcome}"
        color = 0x22C55E if is_win else 0xEF4444
        city_date = ypos.get("city_date", "")
        yes_contracts = int(ypos.get("yes_contracts", 0))
        cost = float(ypos.get("yes_cost", 0))
        no_loss = float(ypos.get("no_loss_amount", 0))

        fields = [
            {"name": "Ticker", "value": f"`{ypos.get('ticker', '')}`", "inline": False},
        ]
        if city_date:
            parts = city_date.split("|") if "|" in city_date else [city_date, ""]
            fields.append({"name": "City", "value": parts[0], "inline": True})

        fields.extend([
            {"name": "Outcome", "value": f"**{outcome}**", "inline": True},
            {"name": "YES Contracts", "value": str(yes_contracts), "inline": True},
            {"name": "Cost", "value": f"${cost:.2f}", "inline": True},
            {"name": "Payout", "value": f"${payout:.2f}", "inline": True},
            {"name": "YES P&L", "value": f"**${pnl:+.2f}**", "inline": True},
            {"name": "Original NO Loss", "value": f"${no_loss:.2f}", "inline": True},
        ])

        embed = {
            "title": title,
            "color": color,
            "fields": fields,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "footer": {"text": "ColdSync"},
        }
        await self._send_embed(embed)

    async def send_daily_summary(self, data: dict):
        phase_names = {1: "Learning", 2: "Standard", 3: "Scaled"}
        phase_label = phase_names.get(data["phase"], str(data["phase"]))
        daily_pnl = data.get("daily_pnl", 0)
        total_pnl = data.get("total_pnl", 0)
        pnl_color = 0x22C55E if daily_pnl >= 0 else 0xEF4444

        embed = {
            "title": "Daily Summary",
            "color": pnl_color,
            "fields": [
                {"name": "Phase", "value": f"{phase_label} ({data['scale_factor']:.0%} scale)", "inline": True},
                {"name": "Balance", "value": f"${data['wallet_balance']:,.2f}", "inline": True},
                {"name": "Free Cash", "value": f"${data['free_cash']:,.2f}", "inline": True},
                {"name": "Unresolved", "value": f"${data['unresolved']:,.2f} ({data['unresolved_pct']:.0%})", "inline": True},
                {"name": "Today's Trades", "value": str(data.get("trades_today", 0)), "inline": True},
                {"name": "Exits", "value": str(data.get("exits_today", 0)), "inline": True},
                {"name": "Resolutions", "value": f"{data.get('resolutions_today', 0)} (W{data['wins']} / L{data['losses']})", "inline": False},
                {"name": "Daily P&L", "value": f"**${daily_pnl:+,.2f}**", "inline": True},
                {"name": "Total P&L", "value": f"**${total_pnl:+,.2f}**", "inline": True},
                {"name": "No Win Rate", "value": f"{data.get('no_win_rate', 0):.1%}", "inline": True},
            ],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "footer": {"text": "ColdSync"},
        }
        await self._send_embed(embed)

    async def send_error(self, message: str):
        embed = {
            "title": "Error",
            "description": f"```{message[:1000]}```",
            "color": 0xEF4444,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "footer": {"text": "ColdSync"},
        }
        await self._send_embed(embed)

    async def send_phase_change(self, old_phase: int, new_phase: int):
        phase_names = {1: "Learning", 2: "Standard", 3: "Scaled"}
        embed = {
            "title": "Phase Upgrade",
            "description": f"**{phase_names.get(old_phase, old_phase)} -> {phase_names.get(new_phase, new_phase)}**\n\nExposure and sizing limits updated.",
            "color": 0xA855F7,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "footer": {"text": "ColdSync"},
        }
        await self._send_embed(embed)

    async def send_bot_started(self, balance: float, phase: int, dry_run: bool):
        phase_names = {1: "Learning", 2: "Standard", 3: "Scaled"}
        mode = "Dry Run" if dry_run else "Live"
        embed = {
            "title": "Bot Started",
            "color": 0x22C55E if not dry_run else 0xEAB308,
            "fields": [
                {"name": "Mode", "value": mode, "inline": True},
                {"name": "Phase", "value": phase_names.get(phase, str(phase)), "inline": True},
                {"name": "Balance", "value": f"${balance:,.2f}", "inline": True},
            ],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "footer": {"text": "ColdSync"},
        }
        await self._send_embed(embed)

    async def send_scan_summary(self, scan_count: int, trades: int, exits: int, bins_scanned: int):
        if trades == 0 and exits == 0:
            return
        embed = {
            "title": f"Scan #{scan_count}",
            "color": 0x6366F1,
            "fields": [
                {"name": "Bins Scanned", "value": str(bins_scanned), "inline": True},
                {"name": "No Buys", "value": str(trades), "inline": True},
                {"name": "Exits", "value": str(exits), "inline": True},
            ],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "footer": {"text": "ColdSync"},
        }
        await self._send_embed(embed)

    async def close(self):
        await self.http.aclose()
