class GameCore:
    def __init__(self):
        self.resources = {"food": 100, "water": 100, "tools": 50}
        self.health = 100
        self.is_alive = True
        self.tick_count = 0

    def tick(self):
        self.tick_count += 1
        self._update_resources()
        self._update_health()
        self._check_survival()

    def _update_resources(self):
        self.resources["food"] -= 5
        self.resources["water"] -= 5
        self.resources["tools"] -= 2

    def _update_health(self):
        if self.resources["food"] < 20:
            self.health -= 10
        if self.resources["water"] < 20:
            self.health -= 10

    def _check_survival(self):
        if self.health <= 0:
            self.is_alive = False

    def report_status(self):
        return {
            "tick": self.tick_count,
            "resources": self.resources,
            "health": self.health,
            "alive": self.is_alive
        }

def main():
    game = GameCore()
    for _ in range(20):
        game.tick()
        print(game.report_status())

if __name__ == "__main__":
    main()