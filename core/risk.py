from datetime import datetime, timedelta, timezone


class RiskController:
    def __init__(self, config, db):
        self.config = config
        self.db = db
        self._scale_factor = 1.0
        self._scale_expires = None
        self._paused_until = None
        self._frozen_cities = {}
        self._bad_structure_count = 0

    @property
    def is_paused(self) -> bool:
        if self._paused_until and datetime.now(timezone.utc) < self._paused_until:
            return True
        return False

    @property
    def scale_factor(self) -> float:
        if self._scale_expires and datetime.now(timezone.utc) > self._scale_expires:
            self._scale_factor = 1.0
        return self._scale_factor

    def is_city_frozen(self, city_date: str) -> bool:
        unfreeze = self._frozen_cities.get(city_date)
        if unfreeze and datetime.now(timezone.utc) < unfreeze:
            return True
        if unfreeze:
            del self._frozen_cities[city_date]
        return False

    async def on_resolution(self, pnl: float, city_date: str, wallet_balance: float):
        now = datetime.now(timezone.utc)

        if pnl < 0:
            daily_losses = await self.db.count_resolution_losses_since(now - timedelta(hours=24))
            daily_loss_amount = await self.db.sum_resolution_losses_since(now - timedelta(hours=24))

            city_losses = await self.db.count_city_losses_today(city_date)
            if city_losses >= self.config.city_freeze_trigger:
                freeze_until = now + timedelta(hours=self.config.city_freeze_hours)
                self._frozen_cities[city_date] = freeze_until
                await self.db.freeze_city(city_date, freeze_until)

            if (daily_losses >= self.config.loss_hard_pause_count
                    or abs(daily_loss_amount) >= wallet_balance * self.config.loss_hard_pause_wallet_pct):
                self._paused_until = now + timedelta(hours=4)
                return

            if daily_losses >= self.config.loss_warning_count:
                self._scale_factor = self.config.loss_warning_size_reduction
                self._scale_expires = now + timedelta(hours=24)

            self._bad_structure_count += 1
            if self._bad_structure_count >= self.config.bad_structure_pause_count:
                self._scale_factor = self.config.bad_structure_size_reduction
                self._scale_expires = now + timedelta(hours=self.config.bad_structure_pause_hours)
                self._bad_structure_count = 0
        else:
            self._bad_structure_count = 0

    async def check_phase_advancement(self) -> bool:
        days_active = await self.db.days_since_start()
        no_win_rate = await self.db.no_bet_win_rate()
        total_pnl = await self.db.total_pnl()
        starting = await self.db.starting_balance()
        total_pnl_pct = total_pnl / starting if starting > 0 else 0

        if self.config.phase == 1:
            if days_active >= self.config.phase_1_min_days and no_win_rate >= self.config.phase_1_min_no_win_rate:
                self.config.phase = 2
                return True
        elif self.config.phase == 2:
            if days_active >= self.config.phase_2_min_days and total_pnl_pct >= self.config.phase_2_min_pnl_pct:
                self.config.phase = 3
                return True
        return False

    async def check_scale_up(self):
        streak = await self.db.consecutive_profitable_days()
        if streak >= self.config.scale_up_streak and self._scale_factor <= 1.0:
            self._scale_factor = self.config.scale_up_factor
            self._scale_expires = None

    async def load_frozen_cities(self):
        self._frozen_cities = await self.db.get_frozen_cities()
