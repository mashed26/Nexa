from nexus_modAPI.nexus import NexusMod, Effects, World, Sounds, Entities

class MegaMod(NexusMod):
    def __init__(self):
        super().__init__(
            mod_id="megamod",
            name="Mega Mod",
            version="2.0",
            author="YourName",
            description="Applies multiple effects and plays sounds based on world time.",
            capabilities=[
                "nexus.actions.apply_effect",
                "nexus.actions.play_sound",
                "R:nexus.events.player_join"
            ]
        )
        self.registerCapabilities()
        self.activate()

    @NexusMod.hook(event="player_join")
    def megaEffect(self, **kwargs):
        player = kwargs.get("player")

        # Base speed effect
        speed_effect = Effects(effect_name="Speed", duration=20*60*60, amplifier=1)
        jump_effect = Effects(effect_name="Jump", duration=20*60*30, amplifier=0)
        
        # Special sound effect
        welcome_sound = Sounds(sound_name="minecraft:entity.player.levelup", volume=1.0, pitch=1.2)

        # Conditional logic based on world time
        if World.getTime() < 1000:
            speed_effect.applyEffect(speed_effect, player=player)
            jump_effect.applyEffect(jump_effect, player=player)
            welcome_sound.playSound(player)
        elif World.getTime() < 6000:
            # Slightly weaker speed in morning
            speed_effect.amplifier = 0
            speed_effect.applyEffect(speed_effect, player=player)
        else:
            # Nighttime fun: only jump boost
            jump_effect.applyEffect(jump_effect, player=player)

        # Nested condition: if health low, grant temporary regeneration
        if player.health < 5:
            regen_effect = Effects(effect_name="Regeneration", duration=20*10, amplifier=1)
            regen_effect.applyEffect(regen_effect, player=player)

        # Multiple sequential API calls: spawn a friendly entity if early morning
        if World.getTime() < 500:
            villager = Entities(entity_type="minecraft:villager", x=player.x, y=player.y, z=player.z)
            villager.spawnEntity()
            