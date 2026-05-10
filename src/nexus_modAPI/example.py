# This is example code of a basic Nexus mod that applies a Speed 2 effect to the player when they join the world.

# To help, a provided pseudocode example of how this would work in Forge is included below.

# Forge pseudocode example:
"""@Mod("speedmod")
public class SpeedMod {

    public SpeedMod() {
        MinecraftForge.EVENT_BUS.register(this);
    }

    @SubscribeEvent
    public void onPlayerJoin(PlayerEvent.PlayerLoggedInEvent event) {
        if (!event.getPlayer().level().isClientSide()) {
            event.getPlayer().addEffect(
                new MobEffectInstance(MobEffects.MOVEMENT_SPEED, 
                                      20 * 60 * 60,  // 1 hour
                                      1));           // Amplifier 1 = Speed II
        }
    }
}"""


from nexus_modAPI.nexus import NexusMod, Effects, World

class SpeedMod(NexusMod):
    def __init__(self):
        super().__init__(
            mod_id="speedmod",
            name="Speed Mod",
            version="1.0",
            author="YourName",
            description="Applies Speed II effect to the player on world join.",
            capabilities=["nexus.actions.apply_effect", "R:nexus.events.player_join"]  # The "R:" prefix indicates this is a required capability. The mod requires mandatory approval of the capabilities it requires, and clients will be unable to play if they reject the capability.
        )
        

    # Not registering nexus.events.player_join throws an error. This is done for security and privacy reasons.
    @NexusMod.hook(event="on_player_join") 
    def applySpeed(self, **kwargs):
        # Create an instance of the Effects class with the appropriate parameters
        speed_effect = Effects(effect_name="Speed", duration=20 * 60 * 60, amplifier=1)
        
        # Apply the effect to the player using the Nexus API
        # apply_effect is an inherited method from the Effect class.
        # Additionally, the variables provided to the hook function (like player) would be passed in as kwargs, so you could also do something like:
        # def applySpeed(self, player):
        #     speed_effect.applyEffect(player)

        #Oh, and safety is included. That means no wrapped conditionals by default. This is overwritable with the parameter "safe=True" in the hook decorator, but you would then be expected to do your own error handling and ensure that your mod doesn't crash the game.

        if World.getTime() < 1000:  # Only apply the effect if it's before time 1000 in the world (early morning)
            speed_effect.applyEffect(speed_effect, player=kwargs.get("player"))