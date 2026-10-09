# Pipeline check: build this, start the game, open the cheat console
# (Ctrl+Shift+C) and type  bluerabbit477.hello
import sims4.commands


@sims4.commands.Command('bluerabbit477.hello', command_type=sims4.commands.CommandType.Live)
def hello(_connection=None):
    output = sims4.commands.CheatOutput(_connection)
    output("Hello from the Sims 4 mods workspace - script mods are loading.")
