from nexus_modAPI.nexus import NexusMod, Effects, World, Sounds, Entities, PersistentData, Player

class GiftingMod(NexusMod):
    def __init__(self):
        super().__init__(
            mod_id="giftingmod",
            name="Gifting",
            version="1.0",
            author="StormCode",
            description="Gives a player scheduled items. If the player is offline, the items will be given when they next log in.",
            capabilities=[
                "nexus.actions.apply_effect",
                "nexus.actions.play_sound",
                "R:nexus.events.player_join",
                "R:nexus.system.persistent_storage",
                "R:nexus.commands.give",
                "R:nexus.commands.custom"

            ]
        )

        self.queuedGifts = PersistentData(self, "gifts") 

    @NexusMod.hook(event="player_join")
    def giftPlayer(self, **kwargs):
        #player = kwargs.get("player")
        player = Player(kwargs.get("player"))

        player_name = player.getName()

        # Check if the player has any queued gifts
        if player_name in self.queuedGifts:
            gifts = self.queuedGifts[player_name]
            for gift in gifts:
                # Give the item to the player using the Nexus command system
                self.executeCommand(f"give {player_name} {gift['item']} {gift['quantity']}")
                # Optionally, play a sound or apply an effect to indicate they received a gift
                Sounds(sound_name="minecraft:entity.player.levelup").playSound(player)
            # Clear the queued gifts for the player
            self.queuedGifts.setData(player_name, [])
    @NexusMod.hook(event="custom_Command_Invoke", command="giftItem", areas=["discord"])
    def giftItem(self, player_name, item, quantity=1):
        # Check if the player is currently online
        player = Player.getPlayerByName(player_name)
        if player:
            # Player is online, give the item immediately
            self.executeCommand(f"give {player_name} {item} {quantity}")
            Sounds(sound_name="minecraft:entity.player.levelup").playSound(player)
        else:
            # Player is offline, queue the gift for when they next log in
            if player_name not in self.queuedGifts:
                # Add a new entry to the list of gifts for this player
                self.queuedGifts.setData(player_name, [])
            #self.queuedGifts[player_name].append({"item": item, "quantity": quantity})
            self.queuedGifts.appendData(player_name, {"item": item, "quantity": quantity})

    """temporary docstring to sketch what the json would look like for storage
    
    {
    "player1": [
        {"item": "minecraft:diamond_sword", "quantity": 1},
        {"item": "minecraft:apple", "quantity": 5}
    ],
    "player2": [
        {"item": "minecraft:bow", "quantity": 1}
    ]
    }
    
    """

    

        