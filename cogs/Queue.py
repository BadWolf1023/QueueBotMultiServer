import discord
from discord.ext import commands, tasks
import json
from dateutil.parser import parse
from datetime import datetime, timedelta
import dill as p
from collections import defaultdict
from cogs import GuildSettings
from Shared import is_lounge
from ExtraChecks import carrot_prohibit_check, lounge_only_check
from builtins import staticmethod
from typing import List
from statistics import mean
from math import sqrt
import random
from discord.ext.commands.cooldowns import BucketType






CHECKMARK_ADDITION = "-\U00002713"
CHECKMARK_ADDITION_LEN = 2
time_print_formatting = "%B %d, %Y at %I:%M%p Eastern Time"


#Here is the hierarchy for this file and its classes:
#AllQueues is a cog that receives commands, it contains 

#There are two timezones: the timezone your staff schedules events in, and your server's timezone
#Set this to the number of hours ahead (or behind) your staff's timezone is from your server's timezone
#This is so that you don't have to adjust your machine clock to accomodate for your staff

#For example, if my staff is supposed to schedule events in ET and my machine is PST, this number would be 3 since ET is 3 hours ahead of my machine's PST
TIME_ADJUSTMENT = timedelta(hours=1)


GUILDS_SCHEDULES = {}

LOUNGE_EXPONENT = 2
mean_of_sum_of_exponent = lambda numbers:mean(map(lambda num : num ** LOUNGE_EXPONENT, numbers))
def calculate_lounge_rating(ratings:List[int]):
    return round(sqrt(mean_of_sum_of_exponent(ratings)))


def calculate_team_rating(ratings:List[int], guild_settings:GuildSettings.GuildSettings):
    if is_lounge(guild_settings.get_guild_id()):
        return calculate_lounge_rating(ratings)
    else:
        return round(mean(ratings))

def get_role_by_name(guild:discord.Guild, role_name):
    if guild is not None:
        role_name = role_name.lower().replace(" ", "")
        for role in guild.roles:
            if role.name.lower().replace(" ", "") == role_name:
                return role
    return None


def shuffle_together(*args):
    """Shuffles in place any number of iterables. Iterables must be of the same length, otherwise an assertion error is thrown"""
    assert len(args) > 0
    arg_length = len(args[0])
    for arg in args:
        assert len(arg) == arg_length #Make sure they are all the same size - would be strange to randomize different length iterables
    
    startingState = random.getstate() #we'll reset the state after each randomization so that the randomization is the same for each iterable
    for arg in args:
        random.setstate(startingState)
        random.shuffle(arg)
    
#Guarantees to not throw an exception
async def safe_send(channel:discord.TextChannel, content=None, embed=None, file=None, delete_after=None):
    try:
        await channel.send(content=content, embed=embed, file=file, delete_after=delete_after)
    except:
        pass
      
async def lockdown(channel:discord.TextChannel):
    overwrite = channel.overwrites_for(channel.guild.default_role)
    overwrite.send_messages = False
    await channel.set_permissions(channel.guild.default_role, overwrite=overwrite)
    await safe_send(channel, "Locked down " + channel.mention)

async def unlockdown(channel:discord.TextChannel):
    overwrite = channel.overwrites_for(channel.guild.default_role)
    overwrite.send_messages = None
    await channel.set_permissions(channel.guild.default_role, overwrite=overwrite)
    await safe_send(channel, "Unlocked " + channel.mention)
    
    
async def temporary_disabled_command(ctx):
    await ctx.send("This command has been temporarily disabled while the bot is in early release. Check again in a few days.")
    raise Exception()

def strip_prefix(message:str, prefix="!"):
    message = message.strip()
    if message.startswith(prefix):
        return message[len(prefix):]

def strip_prefix_and_command(message:str, valid_terms:set, prefix="!"):
    message = strip_prefix(message, prefix)
    args = message.split()
    if len(args) == 0:
        return message
    for term in sorted(valid_terms, key=lambda x:-len(x)):
        if message.lower().startswith(term):
            message = message[len(term):]
            break
    return message.strip()


def get_player_str(player, rating, is_secondary_type, guild_settings:GuildSettings.GuildSettings, add_new_line_end=True):
    
    secondary_name_str = (guild_settings.secondary_rating_description_text if is_secondary_type else guild_settings.primary_rating_description_text).strip()
    
    rating_name_str = (guild_settings.secondary_rating_display_text if is_secondary_type else guild_settings.primary_rating_display_text).strip()
    
    rating_str = "" if (rating is None or not guild_settings.show_rating) else f"({rating}"
    if rating_str != "":
        rating_str += f" {secondary_name_str}" if len(secondary_name_str.strip()) > 0 else ""
        rating_str += f" {rating_name_str}" if len(rating_name_str.strip()) > 0 else ""
        rating_str += ")"
    
    result_str = f"{player.display_name}"
    
    if secondary_name_str != "":
        result_str += f" ({secondary_name_str})"
        
    if rating_str != "":
        result_str += f" {rating_str}"
        
    if add_new_line_end:
        result_str += "\n"
    return result_str
    

def get_team_str(players_dict, team_rating, guild_settings:GuildSettings.GuildSettings, add_line_between_players=False, add_new_line_end=True):
    player_text_list = []
    for player, player_info in players_dict.items():
        cur_player_txt = player.display_name
        is_secondary_type = player_info[-1]
        secondary_name_str = (guild_settings.secondary_rating_description_text if is_secondary_type else guild_settings.primary_rating_description_text).strip()
        
        if secondary_name_str != "":
            cur_player_txt += f" ({secondary_name_str})"
        player_text_list.append(cur_player_txt)
        
    result_str = ", ".join(player_text_list)
    if add_line_between_players:
        result_str = "\n".join(player_text_list)
        
        
    rating_name_str = guild_settings.primary_rating_display_text.strip()
    if guild_settings.show_rating:
        if add_line_between_players:
            result_str += "\n"
        result_str += f" ({team_rating} {rating_name_str.strip()}".rstrip()
        result_str += ")"
    if add_new_line_end:
        result_str += "\n"
    return result_str

def get_squad_str(players_dict, author_name, team_size, guild_settings:GuildSettings.GuildSettings, add_new_line_end=True, generic_one_line=False):
    confirmCount = 0
    playerNum = 1
    result_str = ""
    all_player_strings = []
    
    for player, player_info in players_dict.items():
        is_secondary_type = player_info[2]
        player_str = get_player_str(player, int(player_info[1]), is_secondary_type, guild_settings, add_new_line_end=False)
        if not generic_one_line:
            player_str = f"`{playerNum}.` " + player_str
        
        if player_info[0] is False:
            player_str += " `✘ Unconfirmed`"
        else:
            player_str += " `✓ Confirmed`"
            confirmCount += 1
        all_player_strings.append(player_str)
        playerNum += 1
        
    if generic_one_line:
        result_str += " ".join(all_player_strings)
    else:
        result_str += "\n".join(all_player_strings)
        
    new_line_str_check = "\n" if add_new_line_end else ""

    registered_str = f"{confirmCount}/{team_size} confirmed"
    if confirmCount == team_size:
        registered_str = f"fully registered"
        
    if not generic_one_line:
        return f"`{author_name}'s squad [{registered_str}]`\n" + result_str + new_line_str_check
    else:
        return result_str + f" [{registered_str}]" + new_line_str_check


class IndividualQueue():
    def __init__(self, bot):
        # no commands should work when self.started or self.gathering is False, 
        # except for start, which initializes each of these values.
        self.bot = bot
        self.started = False
        self.gathering = False
        self.making_rooms_run = False
        
        # can either be 5 representing the respective queue size
        self.team_size = 2
        self.teams_per_room = 6
        
                
        # self.waiting is a list of dictionaries, with the keys each corresponding to a
        # Discord member class, and the values being a list with 2 values:
        # index 0 being the player's confirmation status, and index 1 being the player's rating/elo.
        self.waiting = []
        
        # self.list is also a list of dictionaries, with the keys each corresponding to a
        # Discord member class, and the values being the player's rating/elo.
        self.list = []
        
        # contains the avg rating/elo of each confirmed team
        self.teamRatings = []

        #list of Channel objects created by the bot for easy deletion
        self.channels = []
        
        self.is_automated = False
        
        self.queue_channel = None
        
        self.start_time = None
               
        #Specify whether primary leaderboard or secondary leaderboard, necessary for rating/elo lookup
        self.is_primary_leaderboard = True
        
        self.last_used = datetime.now()
        
    @staticmethod
    async def start_input_validation(ctx, queue_type:str, team_size:int, teams_per_room:int, guildSettings):
        default_failure = (False, None)
        valid_queue_types = []
        valid_queue_types_old = []
        if guildSettings.primary_leaderboard_name.strip() != "":
            valid_queue_types.append(guildSettings.primary_leaderboard_name.lower().strip())
            valid_queue_types_old.append(guildSettings.primary_leaderboard_name.strip())
        if guildSettings.secondary_leaderboard_name.strip() != "":
            valid_queue_types.append(guildSettings.secondary_leaderboard_name.lower().strip())
            valid_queue_types_old.append(guildSettings.secondary_leaderboard_name.strip())
        fixed_queue_type = None
                
        if len(valid_queue_types) == 0:
            await ctx.send("You need to set a leaderboard type in your settings to use this command. Do `!queuebot_setup primary_leaderboard_name` to set your leaderboard name.")
        
        queue_type = queue_type.lower()
        
        if queue_type not in valid_queue_types:
            await ctx.send(f"The queue type you entered is invalid; proper values are: {', '.join(valid_queue_types_old)}")
            return default_failure
        else:
            fixed_queue_type = valid_queue_types_old[valid_queue_types.index(queue_type)]
        
        if team_size < 1:
            await ctx.send(f"You must have at least 1 player on each team.")
            return default_failure
        
        if team_size > 100:
            await ctx.send(f"Your team cannot have more than 100 people.")
            return default_failure
        
        if teams_per_room > 100:
            await ctx.send(f"Your cannot have more than 100 teams per room.")
            return default_failure
        
        if teams_per_room < 2:
            if teams_per_room == 1:
                await ctx.send(f"The number of teams per room will be **1**. Unless you know what you're doing, this is probably a mistake.")
            else:
                await ctx.send(f"The number of teams per room cannot be 0.")
                return default_failure
        
        return True, fixed_queue_type
    
    async def ongoing_queue_check(self):
        #If it's not automated, not started, we've already started making the rooms, don't run this
        if not self.is_automated or not self.started or self.making_rooms_run:
            return
        
        cur_time = datetime.now()
        guild_settings = GuildSettings.get_guild_settings(self.queue_channel.guild.id)

        if (self.start_time + guild_settings.extension_time) <= cur_time:
            await self.makeRoomsLogic(self.queue_channel, (cur_time.minute + 1)%60, guild_settings, True)
            return
        
        if self.start_time <= cur_time:
            #check if there are an even amount of teams since we are past the queue time
            numLeftoverTeams = len(self.list) % self.teams_per_room
            if numLeftoverTeams == 0:
                await self.makeRoomsLogic(self.queue_channel, (cur_time.minute + 1)%60, guild_settings, True)
                return
            else:
                if int(cur_time.second / 20) == 0:
                    force_time = self.start_time + guild_settings.extension_time
                    minutes_left = int((force_time - cur_time).seconds/60) + 1
                    x_teams = self.teams_per_room - numLeftoverTeams
                    await safe_send(self.queue_channel, f"Need {x_teams} more team(s) to start immediately. Starting in {minutes_left} minute(s) regardless.")
   
        
    async def sortTeams(self, ctx):
        """Backup command if !makerooms doesn't work; doesn't make channels, just sorts teams by elo/rating"""
        guild_settings = GuildSettings.get_guild_settings(ctx)
        try:
            await self.is_started(ctx)
        except:
            return
        indexes = range(len(self.teamRatings))
        sortTeamsMMR = sorted(zip(self.teamRatings, indexes), reverse=True)
        sortedMMRs = [x for x, _ in sortTeamsMMR]
        sortedTeams = [self.list[i] for i in (x for _, x in sortTeamsMMR)]
        msg = "`Sorted list`\n"
        for i in range(len(sortedTeams)):
            if i > 0 and i % 15 == 0:
                await ctx.send(msg)
                msg = ""
            msg += "`%d.` " % (i+1)
            msg += get_team_str(sortedTeams[i], sortedMMRs[i], guild_settings, add_new_line_end=True)
        await ctx.send(msg)

        
    async def makeRoomsLogic(self, queue_channel:discord.TextChannel, openTime:int, guild_settings:GuildSettings.GuildSettings, startedViaAutomation=False):
        """Sorts squads into rooms based on average elo/rating, creates room channels and adds players to each room channel"""
        if self.making_rooms_run and startedViaAutomation: #Reduce race condition, but also allow manual !makeRooms
            return
        
        if guild_settings.lockdown_on:
            await lockdown(queue_channel)
        
        self.making_rooms_run = True
        if self.gathering:
            self.gathering = False
            await safe_send(queue_channel, "Queue is now closed; players can no longer join or drop from the event")

        numRooms = int(len(self.list) / self.teams_per_room)
        if numRooms == 0:
            await safe_send(queue_channel, "Not enough players to fill a room! Try this command with at least %d teams" % self.teams_per_room)
            return

        if openTime >= 60 or openTime < 0:
            await safe_send(queue_channel, "Please specify a valid time (in minutes) for rooms to open (00-59)")
            return
        startTime = openTime + 10
        while startTime >= 60:
            startTime -= 60
            
        category = queue_channel.category
            
        numTeams = int(numRooms * self.teams_per_room)
        finalList = self.list[0:numTeams]
        finalMMRs = self.teamRatings[0:numTeams]
        
        #Shuffle the lists so that any ties will be random
        shuffle_together(finalList, finalMMRs)

        indexes = range(len(finalMMRs))
        sortTeamsMMR = sorted(zip(finalMMRs, indexes), reverse=True)
        sortedMMRs = [x for x, _ in sortTeamsMMR]
        sortedTeams = [finalList[i] for i in (x for _, x in sortTeamsMMR)]
        for i in range(numRooms):
            #creating room roles and channels
            roomName = f"{guild_settings.created_channel_name}-{i+1}"
            overwrites = {
                queue_channel.guild.default_role: discord.PermissionOverwrite(view_channel=False),
                queue_channel.guild.me: discord.PermissionOverwrite(view_channel=True)
            }
            
            #tries to retrieve all these roles, and add them to the
            #channel overwrites if the role specified in the config file exists
            #TODO: Make sure that roles on the category aren't overwritten by any role they have added to the channels
            role_names_to_add_to_channels = guild_settings.roles_can_see_primary_leaderboard_rooms if self.is_primary_leaderboard else guild_settings.roles_can_see_secondary_leaderboard_rooms
            role_objects_to_add_to_channels = []
            for role_name in role_names_to_add_to_channels:
                discord_role = get_role_by_name(queue_channel.guild, role_name)
                if discord_role is not None:
                    role_objects_to_add_to_channels.append(discord_role)
            for discord_role in role_objects_to_add_to_channels:
                if discord_role is not None:
                    overwrites[discord_role] = discord.PermissionOverwrite(view_channel=True)
            
            
            voice_channel_overwrites = overwrites.copy()
            all_voice_channel_overwrites = []
            msg = "`%s`\n" % roomName
            for j in range(self.teams_per_room):
                index = int(i * self.teams_per_room + j)
                msg += "`%d.` " % (j+1)
                msg += get_team_str(sortedTeams[index], sortedMMRs[index], guild_settings, add_line_between_players=False, add_new_line_end=True)
                
                for player in sortedTeams[index].keys():
                    overwrites[player] = discord.PermissionOverwrite(view_channel=True)
                    
                if guild_settings.create_voice_channels:
                    all_voice_channel_overwrites.append(voice_channel_overwrites.copy())
                    for player in sortedTeams[index].keys():
                        all_voice_channel_overwrites[-1][player] = discord.PermissionOverwrite(view_channel=True)
                    
            roomMsg = msg
            mentions = ""
            for j in range(self.teams_per_room):
                index = int(i * self.teams_per_room + j)
                mentions += " ".join([player.mention for player in sortedTeams[index].keys()])
                mentions += " "
            if guild_settings.send_scoreboard_text:
                scoreboard = "Table: `!scoreboard %d " % self.team_size
                scoreboard_players = []
                for j in range(self.teams_per_room):
                    index = int(i * self.teams_per_room + j)
                    for player in sortedTeams[index]:
                        scoreboard_players.append(player.display_name)
                
                scoreboard += ", ".join(scoreboard_players)
                roomMsg += "%s`\n" % scoreboard
                
            host_str = "Decide a host amongst yourselves; "
            
            roomMsg += ("\n%sRoom open at :%02d, start at :%02d. Make sure you have fun!\n\n"
                        % (host_str, openTime, startTime))
            roomMsg += mentions
            final_text_channel_overwrites = category.overwrites.copy()
            final_text_channel_overwrites.update(overwrites)
            roomChannel = await category.create_text_channel(name=roomName, overwrites=final_text_channel_overwrites)
            for ind, voice_channel_overwrites in enumerate(all_voice_channel_overwrites, 1):
                final_voice_channel_overwrites = category.overwrites.copy()
                final_voice_channel_overwrites.update(voice_channel_overwrites)
                
                vc = await category.create_voice_channel(name=roomName + "-vc-" + str(ind), overwrites=final_voice_channel_overwrites)
                self.channels.append([vc, False])
                
            self.channels.append([roomChannel, False])
            await safe_send(roomChannel, roomMsg)
            await safe_send(queue_channel, msg)
            
        if numTeams < len(self.list):
            missedTeams = self.list[numTeams:len(self.list)]
            missedMMRs = self.teamRatings[numTeams:len(self.list)]
            msg = "`Late teams:`\n"
            for i in range(len(missedTeams)):
                msg += "`%d.` " % (i+1)
                msg += get_team_str(missedTeams[i], missedMMRs[i], guild_settings, add_line_between_players=False, add_new_line_end=True)
            await safe_send(queue_channel, msg)
        
        
           
    # Checks if a user is in a squad currently gathering players;
    # returns False if not found, and returns the squad index in
    # self.waiting if found
    async def check_waiting(self, member: discord.Member):
        if(len(self.waiting) == 0):
            return False
        for i in range(len(self.waiting)):
            for player in reversed(self.waiting[i].keys()):
                # for testing, it's convenient to change player.id
                # and member.id to player.display_name
                # and member.display_name respectively
                # (lets you test with only 2 accounts and changing
                #  nicknames)
                if player == member:
                    return i
        return False
     
    # Checks if a user is in a full squad that has joined the queue;
    # returns False if not found, and returns the squad index in
    # self.list if found
    async def check_list(self, member: discord.Member):
        if (len(self.list) == 0):
            return False
        for i in range(len(self.list)):
            for player in self.list[i].keys():
                # for testing, it's convenient to change player.id
                # and member.id to player.display_name
                # and member.display_name respectively
                # (lets you test with only 2 accounts and changing
                #  nicknames)
                if player == member:
                    return i
        return False
    

    async def is_started(self, ctx):
        if self.started == False:
            await(await ctx.send("Queueing has not started yet.. type !start")).delete(delay=5)
            raise Exception()

    async def is_gathering(self, ctx):
        if self.gathering == False:
            await(await ctx.send("Queueing is closed; players cannot join or drop from the event")).delete(delay=5)
            raise Exception() 
    
    async def launch_queue(self, queue_channel:discord.TextChannel, leaderboard_type:str, team_size: int, teams_per_room:int, guild_settings, is_automated=False, start_time=None):       
        """The caller is responsible to make sure the paramaters are correct"""
        self.started = True
        self.gathering = True
        self.making_rooms_run = False
        self.is_automated = is_automated
        self.team_size = team_size
        self.teams_per_room = teams_per_room
        self.waiting = []
        self.list = []
        self.teamRatings = []
        self.is_primary_leaderboard = leaderboard_type.lower() == guild_settings.primary_leaderboard_name.lower()

        if not is_automated:
            self.is_automated = False
            self.queue_channel = None
            self.start_time = None
        else:
            self.is_automated = True
            self.queue_channel = queue_channel
            self.start_time = start_time
        
        await safe_send(queue_channel, "A %s %dv%d squad queue with %d teams per room has been started%s - %sType `!c`, `!d`, or `!list`" %
                                 (f"{guild_settings.primary_leaderboard_name}" if self.is_primary_leaderboard else f"{guild_settings.secondary_leaderboard_name}",
                                  team_size,
                                  team_size,
                                  teams_per_room,
                                  f", queueing closes in {int(guild_settings.joining_time.total_seconds()/60)} minutes" if self.is_automated else "",
                                  "@here " if guild_settings.should_ping else ""))
        if guild_settings.lockdown_on:
            await unlockdown(queue_channel)
            
    async def start(self, ctx, leaderboard_type:str, team_size: int, teams_per_room:int, guild_settings:GuildSettings.GuildSettings):
        """Start a queue in the channel"""
        was_valid, leaderboard_type_fixed = await IndividualQueue.start_input_validation(ctx, leaderboard_type, team_size, teams_per_room, guild_settings)
        if not was_valid:
            return False
        self.is_automated = False
        await self.launch_queue(ctx.channel, leaderboard_type_fixed, team_size, teams_per_room, guild_settings)
        
    
    async def can(self, ctx, members, guild_settings:GuildSettings.GuildSettings):
        """Tag your partners to invite them to a queue or accept a invitation to join a queue"""
        #can_bag = ctx.invoked_with.lower() in {'cb', 'canbag', 'b', 'bag'}
        try:
            await self.is_started(ctx)
            await self.is_gathering(ctx)
        except:
            return
        if self.team_size == 1 and len(members) > 0:
            await ctx.send("The number of people per team is 1. Don't tag anyone (just !c)."
                           % (self.team_size-1))
            return
            
        elif len(members) > 0 and len(members) < self.team_size - 1:
            await ctx.send("You didn't tag the correct number of people for this format (%d)"
                           % (self.team_size-1))
            return

        sheet = self.bot.get_cog('Elo')

        # checking if message author is already in the queue
        checkWait = await self.check_waiting(ctx.author)
        checkList = await self.check_list(ctx.author)
        if checkWait is not False:
            if self.waiting[checkWait][ctx.author][0] == True:
                await ctx.send("You have already confirmed for this event; type `!d` to drop")  
                return
        if checkList is not False:
            await ctx.send("You have already confirmed for this event (list); type `!d` to drop")  
            return
            

        # logic for when no players are tagged and it is not an FFA
        if len(members) == 0 and self.team_size > 1:
            #runs if message author has been invited to squad
            #but hasn't confirmed
            if checkWait is not False:
                self.waiting[checkWait][ctx.author][0] = True
                confirmedPlayers = []
                missingPlayers = []
                for player in self.waiting[checkWait].keys():
                    if self.waiting[checkWait][player][0] == True:
                        confirmedPlayers.append(player)
                    else:
                        missingPlayers.append(player)
                #TODO:Come back and fix this - not baggers anymore
                bagger_str = "as a bagger " if self.waiting[checkWait][ctx.author][2] else ""
                string = ("Successfully confirmed for your squad %s[%d/%d]\n"
                          % (bagger_str, len(confirmedPlayers), self.team_size))
                if len(missingPlayers) > 0:
                    string += "Missing players: "
                    string += ", ".join([player.display_name for player in missingPlayers])
                
                
                #if player is the last one to confirm for their squad,
                #add them to the queue list
                if len(missingPlayers) == 0:
                    squad = self.waiting[checkWait]
                    squad2 = {}
                    teamMsg = ""
                    ratings = []
                    for player in squad.keys():
                        playerMMR = int(squad[player][1])
                        _can_bag = squad[player][2]
                        squad2[player] = [playerMMR, _can_bag]
                        ratings.append(playerMMR)
                        teamMsg += get_player_str(player, int(playerMMR), _can_bag, guild_settings)
                    self.teamRatings.append(calculate_team_rating(ratings, guild_settings))
                    self.waiting.pop(checkWait)
                    self.list.append(squad2)
                    
                    string += "Squad successfully added to queue `[%d team%s]`:\n%s" % (len(self.list), "s" if len(self.list) > 1 else "", teamMsg)
                
                await ctx.send(string)
                await self.ongoing_queue_check()
                return
            
            await ctx.send("You didn't tag the correct number of people for this format (%d)"
                           % (self.team_size-1))
            return

        # Input validation for tagged members; checks if each tagged member is already
        # in a squad, as well as checks if any of them are duplicates
        for member in members:
            checkWait = await self.check_waiting(member)
            checkList = await self.check_list(member)
            if checkWait is not False or checkList is not False:
                msg = ("%s is already confirmed for a squad for this event `("
                               % (member.display_name))
                if checkWait is not False:
                    msg += ", ".join([player.display_name for player in self.waiting[checkWait].keys()])
                else:
                    msg += ", ".join([player.display_name for player in self.list[checkList].keys()])
                msg += ")` They should type `!d` if this is in error."
                await ctx.send(msg)
                return
            if member == ctx.author:
                await ctx.send("Duplicate players are not allowed for a squad, please try again")
                return
        if len(set(members)) < len(members):
            await ctx.send("Duplicate players are not allowed for a squad, please try again")
            return
            
        # logic for when the correct number of arguments are supplied
        # (self.team_size - 1)
        num_secondary_players = guild_settings.primary_leaderboard_num_secondary_players if self.is_primary_leaderboard else guild_settings.secondary_leaderboard_num_secondary_players
        all_primary_players = [ctx.author] + (members[:-num_secondary_players] if num_secondary_players > 0 else members)
        all_secondary_players = members[-num_secondary_players:] if num_secondary_players > 0 else []
        players = {}
        primaryPlayerMMRs = await sheet.mmr(ctx, all_primary_players, self.is_primary_leaderboard)
        
        if primaryPlayerMMRs is False:
            return
        for player, mmr in primaryPlayerMMRs.items():
            if mmr is False:
                rating_name = guild_settings.primary_rating_display_text if guild_settings.primary_rating_display_text.strip() != "" else "Elo/Rating"
                await(await ctx.send(f"Error: {rating_name} for player {player.display_name} cannot be found! Placement players are not allowed to queue. If you are not placement, please contact a staff member for help")).delete(delay=10)
                return
            players[player] = [False, primaryPlayerMMRs[player], False]
        players[ctx.author][0] = True #Person who initiated the squad is automatically confirmed
        
            
        secondaryPlayerMMRs = await sheet.mmr(ctx, all_secondary_players, self.is_primary_leaderboard, False)
        if secondaryPlayerMMRs is False:
            return
        for player, mmr in secondaryPlayerMMRs.items():
            if mmr is False:
                rating_name = guild_settings.secondary_rating_display_text if guild_settings.primary_rating_display_text.strip() != "" else "Elo/Rating"
                await(await ctx.send(f"Error: {rating_name} for player {player.display_name} cannot be found! Placement players are not allowed to queue. If you are not placement, please contact a staff member for help")).delete(delay=10)
                return
            players[player] = [False, secondaryPlayerMMRs[player], True]
            
        #When not FFA, add all players to waiting list and send squad message
        if self.team_size > 1:
            self.waiting.append(players)
            msg = "%s has created a squad with " % ctx.author.display_name
            
            player_strs = []
            for player, info in list(players.items())[1:]:
                is_secondary_type = info[2]
                secondary_name_str = (guild_settings.secondary_rating_description_text if is_secondary_type else guild_settings.primary_rating_description_text).strip()
                
                player_str = player.display_name
                if secondary_name_str != "":
                    player_str += f" ({secondary_name_str})"
                player_strs.append(player_str)
            
            msg += ", ".join(player_strs)
            msg += "; each player must type `!c` to join the queue [1/%d]" % (self.team_size)
            await(await ctx.send(msg)).delete(delay=10)
        else: #When FFA, immediately confirm them, add their rating, and send confirmation message
            ratings = []
            teamMsg = ""
            for player, player_info in players.items():
                player_info.pop(0)
                ratings.append(player_info[0])
                _can_bag = player_info[1]
                teamMsg = get_player_str(player, int(player_info[0]), _can_bag, guild_settings)

            
            self.teamRatings.append(calculate_team_rating(ratings, guild_settings))
            self.list.append(players)
            string = "Squad successfully added to queue `[%d team%s]`:\n%s" % (len(self.list), "s" if len(self.list) > 1 else "", teamMsg)
                
            await ctx.send(string)
            await self.ongoing_queue_check()
            return
            
            
    async def drop(self, ctx, guild_settings:GuildSettings.GuildSettings):
        """Remove your squad from a queue"""
        try:
            await self.is_started(ctx)
            await self.is_gathering(ctx)
        except:
            return

        checkWait = await self.check_waiting(ctx.author)
        checkList = await self.check_list(ctx.author)
        # "is" instead of "==" is essential here, otherwise if
        # i=0 is returned, it will think it's False
        if checkWait is False and checkList is False:
            await(await ctx.send("You are not currently in a squad for this event; type `!c @partnerNames`")).delete(delay=5)
            return
        if checkWait is not False:
            droppedTeam = self.waiting.pop(checkWait)
            fromStr = " from unfilled squads"
        else:
            droppedTeam = self.list.pop(checkList)
            self.teamRatings.pop(checkList)
            fromStr = " from queue list"
        string = "Removed team "
        string += ", ".join([player.display_name for player in droppedTeam.keys()])
        string += fromStr
        await(await ctx.send(string)).delete(delay=5)
        
    async def remove(self, ctx, num: int, guild_settings:GuildSettings.GuildSettings):
        """Removes the given squad ID from the queue list"""
        try:
            await self.is_started(ctx)
        except:
            return
        if num > len(self.list) or num < 1:
            await(await ctx.send("Invalid squad ID; there are %d squads in the queue"
                                 % len(self.list))).delete(delay=10)
            return
        squad = self.list.pop(num-1)
        self.teamRatings.pop(num-1)
        await ctx.send("Removed squad %s from queue list"
                       % (", ".join([player.display_name for player in squad.keys()])))

    async def close(self, ctx, guild_settings:GuildSettings.GuildSettings):
        """Close the queue so players can't join or drop"""
        try:
            await self.is_started(ctx)
            await self.is_gathering(ctx)
        except:
            return
        self.gathering = False
        self.is_automated = False
        await ctx.send("Queue is now closed; players can no longer join or drop from the event")
        if guild_settings.lockdown_on:
            await lockdown(ctx.channel)
        
    async def open(self, ctx, guild_settings:GuildSettings.GuildSettings):
        """Reopen the queue so that players can join and drop"""
        try:
            await self.is_started(ctx)
        except:
            return
        if self.gathering is True:
            await(await ctx.send("Queue is already open; players can join and drop from the event")
                  ).delete(delay=5)
            return
        self.gathering = True
        self.is_automated = False
        await ctx.send("Queue is now open; players can join and drop from the event")
        if guild_settings.lockdown_on:
            await unlockdown(ctx.channel)
        
    async def end(self, ctx, guild_settings:GuildSettings.GuildSettings):
        """End the queue"""
        try:
            await self.is_started(ctx)
        except:
            return
        try:
            for i in range(len(self.channels)-1, -1, -1):
                await self.channels[i][0].delete()
                self.channels.pop(i)
        except:
            pass
        self.started = False
        self.gathering = False
        self.making_rooms_run = False
        self.is_automated = False
        self.queue_channel = None
        self.start_time = None
        self.waiting = []
        self.list = []
        self.teamRatings = []
        self.is_primary_leaderboard = True
        await ctx.send("%s has ended the queue" % ctx.author.display_name)
        if guild_settings.lockdown_on:
            await lockdown(ctx.channel)
        
    async def _list(self, ctx, guild_settings:GuildSettings.GuildSettings):
        """Display the list of confirmed squads for a queue"""
        try:
            await self.is_started(ctx)
        except:
            return
        if len(self.list) == 0:
            await(await ctx.send("There are no squads in the queue - confirm %d players to join" % (self.team_size))).delete(delay=5)
            return
        msgs = ["`Queue List`\n"]
        for i in range(len(self.list)):
            #safeguard against potentially reaching 2000-char msg limit
            addition = "`%d.` " % (i+1)
            addition += get_team_str(self.list[i], self.teamRatings[i], guild_settings)
            if len(msgs[-1])+len(addition) >= 2000:
                msgs.append("")
        
            msgs[-1] += addition
        
        addition = ""
        if(len(self.list) % (self.teams_per_room) != 0):
            addition = ("`[%d/%d] teams for %d full rooms`"
                    % ((len(self.list) % self.teams_per_room), self.teams_per_room, int(len(self.list) / (self.teams_per_room))+1))
        if len(msgs[-1])+len(addition) >= 2000:
            msgs[-1].append(addition)
        else:
            msgs[-1] += addition
            
        for msg in msgs:
            await ctx.send(msg)
            
    async def unconfirmedsquads(self, ctx, guild_settings:GuildSettings.GuildSettings):
        """Display all unconfirmed squads for a queue"""
        try:
            await self.is_started(ctx)
        except:
            return
        if len(self.waiting) == 0:
            await(await ctx.send("There are no unconfirmed squads.")).delete(delay=5)
            return
        msgs = ["`Unconfirmed Squads`\n"]
        for i in range(len(self.waiting)):
            #safeguard against potentially reaching 2000-char msg limit
            addition = f"`{i+1}.` "
            
            addition += get_squad_str(self.waiting[i], "", self.team_size, guild_settings, add_new_line_end=True, generic_one_line=True)
            if len(msgs[-1])+len(addition) >= 2000:
                msgs.append("")
        
            msgs[-1] += addition
        
        addition = ""
        if(len(self.list) % (self.teams_per_room) != 0):
            addition = ("`[%d/%d] teams for %d full rooms`"
                    % ((len(self.list) % self.teams_per_room), self.teams_per_room, int(len(self.list) / (self.teams_per_room))+1))
        if len(msgs[-1])+len(addition) >= 2000:
            msgs[-1].append(addition)
        else:
            msgs[-1] += addition
            
        for msg in msgs:
            await ctx.send(msg)
        
    async def squad(self, ctx, guild_settings:GuildSettings.GuildSettings):
        """Displays information about your squad for a queue"""
        try:
            await self.is_started(ctx)
        except:
            return
        checkWait = await self.check_waiting(ctx.author)
        checkList = await self.check_list(ctx.author)
        if checkWait is False and checkList is False:
            await(await ctx.send("You are not currently in a squad for this event; type `!c @partnerNames`")
                  ).delete(delay=5)
            return
        
        if checkWait is not False:
            myTeam = self.waiting[checkWait]

        else:
            myTeam = {}
            for player, player_info in self.list[checkList].items():
                myTeam[player] = [True] + player_info
        
        listString = get_squad_str(myTeam, ctx.author.display_name, self.team_size, guild_settings, add_new_line_end=False)
        await(await ctx.send(listString)).delete(delay=30)

    async def makeRooms(self, ctx, openTime: int, guild_settings:GuildSettings.GuildSettings):
        try:
            await self.is_started(ctx)
        except:
            return
        await self.makeRoomsLogic(ctx.channel, openTime, guild_settings)

class Scheduled_Event():
    def __init__(self, leaderboard_type, team_size, teams_per_room, queue_close_time, started, start_channel_id, server_id):
        self.leaderboard_type = leaderboard_type
        self.team_size = team_size
        self.teams_per_room = teams_per_room
        self.queue_close_time = queue_close_time
        self.started = started
        self.start_channel_id = start_channel_id
        self.server_id = server_id
    
    def get_event_str(self, bot):
        guild_settings = GuildSettings.get_guild_settings(self.server_id)
        
        queue_close_time_EST = self.queue_close_time + TIME_ADJUSTMENT
        queue_close_time_EST_str = queue_close_time_EST.strftime(time_print_formatting)
        queue_open_time_EST = queue_close_time_EST - guild_settings.joining_time
        queue_open_time_EST_str = queue_open_time_EST.strftime(time_print_formatting)
        GuildSettings.get_guild_settings(self.server_id)
        channel = None
        try:
            channel = bot.get_channel(self.start_channel_id)
        except:
            pass
        return f"{self.leaderboard_type} {self.team_size}v{self.team_size}, {self.teams_per_room} teams per room, queueing in {'#invalid-channel' if channel is None else channel.mention}" + "\n\t\t" + f"- Queueing opens at {queue_open_time_EST_str}" + "\n\t\t" + f"- Queueing closes at {queue_close_time_EST_str}"
        
        
        
        
        
class Queue(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        with open('./config.json', 'r') as cjson:
            self.config = json.load(cjson)

        
        
        #Load in the schedule from the pkl
        self.scheduled_events = self.load_pkl_schedule()
        self.guildQueues = defaultdict(lambda:defaultdict(lambda: IndividualQueue(bot)))
        self._scheduler_task = self.sqscheduler.start()
        

    def get_guilds_queues(self, ctx):
        if isinstance(ctx, str):
            return self.guildQueues[ctx]
        elif isinstance(ctx, int):
            return self.guildQueues[str(ctx)]
        return self.guildQueues[str(ctx.guild.id)]
    
    def get_queue_create(self, ctx, guilds_queues):
        if isinstance(ctx, str):
            return guilds_queues[ctx]
        elif isinstance(ctx, int):
            return guilds_queues[str(ctx)]
        return guilds_queues[str(ctx.channel.id)]
        
        
        
    async def scheduler_queue_start(self):
        """Functions that tries to launch scheduled queues - Note that it won't launch any scheduled queues
        if an there is already a queue ongoing, instead it will send an error message and delete that event from the schedule"""
        cur_time = datetime.now()
        
        for guild_id, scheduled_events in self.scheduled_events.items():
            try:
                guild_settings = GuildSettings.get_guild_settings(guild_id)
                to_remove = [] #Keep a list of indexes to remove - can't remove while iterating
                for ind, event in enumerate(scheduled_events):
                    if (event.queue_close_time - guild_settings.joining_time) < cur_time:
                        queue_chan = self.bot.get_channel(event.start_channel_id)
                        to_remove.append(ind)
                        if queue_chan == None: #cannot see the queue channel, no where to send an error message, must silently fail
                            pass
                        else:
                            individual_queue_for_channel = self.get_queue_create(queue_chan.id, self.get_guilds_queues(guild_id))
                            if individual_queue_for_channel.started or individual_queue_for_channel.gathering: #We can't start a new event while the current event is already going
                                await queue_chan.send(f"Because there is an ongoing event in this channel right now, the following event has been removed:\n{event.get_event_str(self.bot)}\n")
                            else:
                                try:    
                                    await individual_queue_for_channel.launch_queue(queue_chan, event.leaderboard_type, event.team_size, event.teams_per_room, guild_settings, True, event.queue_close_time)
                                except:
                                    pass
                for ind in reversed(to_remove):
                    del scheduled_events[ind]
            except Exception as e: #A lot of stuff can go wrong, it's important that we don't let failure for one guild cause failure for another guild
                print(e)
            
    async def check_ongoing_queues(self):
        for guild_id, guilds_individual_queues in self.guildQueues.items():
            try:
                for _, individual_queue in guilds_individual_queues.items():
                    try:
                        await individual_queue.ongoing_queue_check()
                    except Exception as e: #A lot of stuff can go wrong, it's important that we don't let failure for one guild cause failure for another guild
                        print(e)
            except Exception as e: #A lot of stuff can go wrong, it's important that we don't let failure for one guild cause failure for another guild
                print(e)
            
            
        
    @tasks.loop(seconds=20.0)
    async def sqscheduler(self):
        """Scheduler that checks if it should start queues and close them"""
        #It may seem silly to do try/except Exception, but this coroutine **cannot** fail
        #This coroutine *silently* fails and stops if exceptions aren't caught - an annoying abstraction of asyncio
        #This is unacceptable considering people are relying on these queues to run, so we will not allow this routine to stop
        try:
            await self.scheduler_queue_start()
        except Exception as e:
            print(e)
            
        try:
            await self.check_ongoing_queues()
        except Exception as e:
            print(e)
        
        
        
    @commands.command(aliases=['c'])
    @commands.max_concurrency(number=1, per=BucketType.guild, wait=True)
    @commands.guild_only()
    @carrot_prohibit_check()
    @GuildSettings.has_guild_settings_check()
    async def can(self, ctx, members: commands.Greedy[discord.Member]):
        """Tag your partners to invite them to a queue or accept a invitation to join a queue"""
        guild_settings = GuildSettings.get_guild_settings(ctx)    
        guilds_queues = self.get_guilds_queues(ctx)
        await self.get_queue_create(ctx, guilds_queues).can(ctx, members, guild_settings)
            
           
    @commands.command(aliases=['d'])
    @commands.max_concurrency(number=1,per=BucketType.guild,wait=True)
    @commands.guild_only()
    @carrot_prohibit_check()
    @commands.cooldown(1, 15, commands.BucketType.member)
    @GuildSettings.has_guild_settings_check()
    async def drop(self, ctx):
        """Remove your squad from a queue"""
        guild_settings = GuildSettings.get_guild_settings(ctx)        
        guilds_queues = self.get_guilds_queues(ctx)
        await self.get_queue_create(ctx, guilds_queues).drop(ctx, guild_settings)

    @commands.command(aliases=['r'])
    @commands.max_concurrency(number=1,per=BucketType.guild,wait=True)
    @commands.guild_only()
    @carrot_prohibit_check()
    @GuildSettings.has_guild_settings_check()
    @GuildSettings.has_roles_check()
    async def remove(self, ctx, num: int):
        """Removes the given squad ID from the queue list"""
        guild_settings = GuildSettings.get_guild_settings(ctx)        
        guilds_queues = self.get_guilds_queues(ctx)
        await self.get_queue_create(ctx, guilds_queues).remove(ctx, num, guild_settings)

    @commands.command()
    @commands.guild_only()
    @carrot_prohibit_check()
    @GuildSettings.has_guild_settings_check()
    @GuildSettings.has_roles_check()
    async def start(self, ctx, track_type:str, team_size: int, teams_per_room:int):
        """Start a queue in the channel defined by the config file"""
        guild_settings = GuildSettings.get_guild_settings(ctx)        
        guilds_queues = self.get_guilds_queues(ctx)
        await self.get_queue_create(ctx, guilds_queues).start(ctx, track_type, team_size, teams_per_room, guild_settings)
    
    
    @commands.command()
    @commands.guild_only()
    @carrot_prohibit_check()
    @GuildSettings.has_guild_settings_check()
    @GuildSettings.has_roles_check()
    async def close(self, ctx):
        """Close the queue so players can't join or drop"""
        guild_settings = GuildSettings.get_guild_settings(ctx)        
        guilds_queues = self.get_guilds_queues(ctx)
        await self.get_queue_create(ctx, guilds_queues).close(ctx, guild_settings)

    @commands.command()
    @commands.guild_only()
    @carrot_prohibit_check()
    @GuildSettings.has_guild_settings_check()
    @GuildSettings.has_roles_check()
    async def open(self, ctx):
        """Reopen the queue so that players can join and drop"""
        guild_settings = GuildSettings.get_guild_settings(ctx)        
        guilds_queues = self.get_guilds_queues(ctx)
        await self.get_queue_create(ctx, guilds_queues).open(ctx, guild_settings)

    @commands.command()
    @commands.guild_only()
    @carrot_prohibit_check()
    @GuildSettings.has_guild_settings_check()
    @GuildSettings.has_roles_check()
    async def end(self, ctx):
        """End the queue"""
        guild_settings = GuildSettings.get_guild_settings(ctx)        
        guilds_queues = self.get_guilds_queues(ctx)
        await self.get_queue_create(ctx, guilds_queues).end(ctx, guild_settings)
            

    @commands.command(aliases=['l'])
    @commands.cooldown(1, 60, commands.BucketType.channel)
    @commands.guild_only()
    @carrot_prohibit_check()
    @GuildSettings.has_guild_settings_check()
    async def list(self, ctx):
        """Display the list of confirmed squads for a queue"""
        guild_settings = GuildSettings.get_guild_settings(ctx)        
        guilds_queues = self.get_guilds_queues(ctx)
        await self.get_queue_create(ctx, guilds_queues)._list(ctx, guild_settings)
        
    @commands.command(aliases=['us', 'ul', 'unconfirmedlist', 'unconfirmedsquads'])
    @commands.cooldown(1, 60, commands.BucketType.channel)
    @commands.guild_only()
    @carrot_prohibit_check()
    @GuildSettings.has_guild_settings_check()
    async def pending(self, ctx):
        """Display the list of confirmed squads for a queue"""
        guild_settings = GuildSettings.get_guild_settings(ctx)        
        guilds_queues = self.get_guilds_queues(ctx)
        await self.get_queue_create(ctx, guilds_queues).unconfirmedsquads(ctx, guild_settings)

    @commands.command()
    @commands.cooldown(1, 30, commands.BucketType.member)
    @commands.guild_only()
    @carrot_prohibit_check()
    @GuildSettings.has_guild_settings_check()
    async def squad(self, ctx):
        """Displays information about your squad for a queue"""
        guild_settings = GuildSettings.get_guild_settings(ctx)        
        guilds_queues = self.get_guilds_queues(ctx)
        await self.get_queue_create(ctx, guilds_queues).squad(ctx, guild_settings)


    @commands.command()
    @commands.bot_has_guild_permissions(manage_channels=True)
    @commands.guild_only()
    @carrot_prohibit_check()
    @GuildSettings.has_guild_settings_check()
    @GuildSettings.has_roles_check()
    async def makeRooms(self, ctx, openTime: int):
        guild_settings = GuildSettings.get_guild_settings(ctx)        
        guilds_queues = self.get_guilds_queues(ctx)
        await self.get_queue_create(ctx, guilds_queues).makeRooms(ctx, openTime, guild_settings)
        
    
    @commands.command()
    @commands.guild_only()
    @carrot_prohibit_check()
    @commands.bot_has_guild_permissions(manage_channels=True)
    async def finish(self, ctx):
        """Finishes the room by adding a checkmark to the channel. Anyone in the room can call this command."""
        current_channel = ctx.channel
        guilds_queues = self.get_guilds_queues(ctx)
        try:
            for guild_queue in guilds_queues.values():
                for index, (channel, isFinished) in enumerate(guild_queue.channels):
                    if current_channel == channel:
                        if not isFinished:
                            await current_channel.edit(name=current_channel.name + CHECKMARK_ADDITION)
                            self.events_channels[index] = [current_channel, True]
                        return
        except: #Because this iterates over other events, it could throw an exception if they change during iteration, or a key error
            pass
       
                   
                                      
    @commands.command()
    @commands.guild_only()
    @carrot_prohibit_check()
    @commands.max_concurrency(number=1,wait=True)
    @GuildSettings.has_guild_settings_check()
    @GuildSettings.has_roles_check()
    async def schedule(self, ctx, queue_channel:discord.TextChannel, leaderboard_type:str, team_size: int, teams_per_room:int, schedule_time:str):
        """Schedules a room in the future so that the staff doesn't have to be online to open the queue and make the rooms"""
        guild_settings = GuildSettings.get_guild_settings(ctx)        
        scheduled_events = self.scheduled_events[str(ctx.guild.id)]
        was_valid, leaderboard_type_fixed = await IndividualQueue.start_input_validation(ctx, leaderboard_type, team_size, teams_per_room, guild_settings)
        if not was_valid:
            return False
        
        if ctx.guild != queue_channel.guild:
            await ctx.send("You cannot schedule a squad queue event for a different server.")
            return
        
        schedule_time = " ".join(ctx.message.content.split(" ")[5:])
        
        
        try:
            actual_time = parse(schedule_time)
            actual_time = actual_time - TIME_ADJUSTMENT
            if queue_channel == None:
                await ctx.send("I can't see the queue channel, so I can't schedule this event.")
                return

            event = Scheduled_Event(leaderboard_type_fixed, team_size, teams_per_room, actual_time, False, queue_channel.id, ctx.guild.id)
            
            scheduled_events.append(event)
            scheduled_events.sort(key=lambda _event: _event.queue_close_time)
            await ctx.send(f"Scheduled:\n{event.get_event_str(self.bot)}")

        except (ValueError, OverflowError):
            await ctx.send("I couldn't figure out the date and time for your event. Try making it a bit more clear for me.")
        self.pkl_schedule()
        
        
    @commands.command()
    @commands.guild_only()
    @carrot_prohibit_check()
    @GuildSettings.has_guild_settings_check()
    @GuildSettings.has_roles_check()
    async def view_schedule(self, ctx):
        """Displays the schedule"""
        scheduled_events = self.scheduled_events[str(ctx.guild.id)]
        
        if len(scheduled_events) == 0:
            await ctx.send("There are currently no schedule events. Do `!schedule` to schedule a future event.")
        else:
            event_str = ""
            for ind, this_event in enumerate(scheduled_events, 1):
                event_str += f"`{ind}.` {this_event.get_event_str(self.bot)}\n"
            event_str += "\nDo `!remove_event` to remove that event from the schedule."
            await ctx.send(event_str)
            
    @commands.command()
    @commands.guild_only()
    @carrot_prohibit_check()
    @commands.max_concurrency(number=1,wait=True)
    @GuildSettings.has_guild_settings_check()
    @GuildSettings.has_roles_check()
    async def remove_event(self, ctx, event_num: int):
        """Removes an event from the schedule"""
        scheduled_events = self.scheduled_events[str(ctx.guild.id)]

        if event_num < 1 or event_num > len(scheduled_events):
            await ctx.send("This event number isn't in the schedule. Do `!view_schedule` to see the scheduled events.")
        else:
            removed_event = scheduled_events.pop(event_num-1)
            await ctx.send(f"Removed:\n`{event_num}.` {removed_event.get_event_str(self.bot)}")
        self.pkl_schedule()
        
        
        

    
    
    def pkl_schedule(self):
        pkl_dump_path = "schedule_backup.pkl"
        with open(pkl_dump_path, "wb") as pickle_out:
            try:
                p.dump(self.scheduled_events, pickle_out)
            except:
                print("Could not dump pickle for scheduled events.")
                
    def load_pkl_schedule(self):
        scheduled_events = defaultdict(list)
        try:
            with open("schedule_backup.pkl", "rb") as pickle_in:
                try:
                    scheduled_events = p.load(pickle_in)
                    if scheduled_events == None:
                        scheduled_events = defaultdict(list)
                except:
                    print("Could not read in pickle for schedule_backup.pkl data.")
                    scheduled_events = defaultdict(list)
        except:
            print("schedule_backup.pkl does not exist, so no events loaded in. Will create when events are scheduled.")         
            scheduled_events = defaultdict(list)
        return scheduled_events
            
    @commands.command()
    @commands.guild_only()
    @carrot_prohibit_check()
    @GuildSettings.has_guild_settings_check()
    @GuildSettings.has_roles_check()
    async def sortTeams(self, ctx):
        """Backup command if !makerooms doesn't work; doesn't make channels, just sorts teams by elo/rating"""
        temporary_disabled_command(ctx)
        guild_settings = GuildSettings.get_guild_settings(ctx)
        guilds_queues = self.get_guilds_queues(ctx)
        await guilds_queues.sortTeams(ctx, guild_settings)
    
    
    async def send_stats_embed(self, ctx, is_primary_rating, track_type):
        guild_settings = GuildSettings.get_guild_settings(ctx)
        is_primary_leaderboard = None
        if guild_settings.primary_leaderboard_name.lower() == track_type.lower():
            is_primary_leaderboard = True
        elif guild_settings.secondary_leaderboard_name.lower() == track_type.lower():
            is_primary_leaderboard = False
        
        valid_leaderboard_types = guild_settings.get_valid_leaderboard_types()
        if is_primary_leaderboard is None:
            await ctx.send("Put a valid leaderboard type: " + ", ".join(valid_leaderboard_types) + f"\n*Example: !{ctx.invoked_with} {guild_settings.primary_leaderboard_name} Jacob*", delete_after=10)
            return
        
        stats_description = "War Runner Stats" if is_primary_rating else "War Bagger Stats"
        stats_description_end = (" - " + (guild_settings.primary_leaderboard_name if is_primary_leaderboard else guild_settings.secondary_leaderboard_name)) if guild_settings.secondary_leaderboard_on else ""
        for_who = [ctx.author.display_name]
        all_args = ctx.message.content.split()
        if len(ctx.args[1:]) < len(all_args): #They are trying to look someone up, they provided a name
            for_who = [" ".join(all_args[len(ctx.args[1:]):])]
            
        player_stats_dict = await self.bot.get_cog('Elo').stats(ctx.channel, for_who, is_primary_leaderboard, is_primary_rating)
        if player_stats_dict is None or len(player_stats_dict) != 1:
            return
        player_name, player_stats = next(iter(player_stats_dict.items()))
        if player_stats is False:
            await ctx.send(f"Could not find {guild_settings.primary_leaderboard_name if is_primary_leaderboard else guild_settings.secondary_leaderboard_name} {stats_description} for the specified player.", delete_after=30)
            return
        
        await loung_stats_send_with_ranking_icon(ctx, player_name, player_stats, stats_description+stats_description_end, is_primary_rating)
        
    
    @commands.command()
    @commands.guild_only()
    @lounge_only_check()
    @commands.cooldown(1, 30, commands.BucketType.member)
    @GuildSettings.has_guild_settings_check()
    async def baggerstats(self, ctx, track_type:str):
        await self.send_stats_embed(ctx, False, track_type)
        
    @commands.command()
    @commands.guild_only()
    @lounge_only_check()
    @commands.cooldown(1, 30, commands.BucketType.member)
    @GuildSettings.has_guild_settings_check()
    async def stats(self, ctx, track_type:str):
        await self.send_stats_embed(ctx, True, track_type)
        
        

async def elo_check(bot, message: discord.Message):
    if message.content == None or len(message.content) == 0 or message.content.strip() == '!':
        return
    if not GuildSettings.has_guild_settings(message):
        return
    guild_settings = GuildSettings.get_guild_settings(str(message.guild.id))
    if not guild_settings.rating_command_on:
        return
    lookup = False
    is_primary_leaderboard = None
    is_primary_rating = None
    for_who = ""
    title = ""
    title_end = ""
    if message.content.lower().startswith('!' + guild_settings.primary_rating_command.lower()) or \
    (message.content.lower().startswith('^' + guild_settings.primary_rating_command.lower()) and is_lounge(message.guild.id)):
        for_who = strip_prefix_and_command(message.content, {guild_settings.primary_rating_command.lower()}, message.content[0])
        if guild_settings.secondary_leaderboard_on:
            if not ((guild_settings.primary_leaderboard_name != "" and for_who.lower().startswith(guild_settings.primary_leaderboard_name.lower()))\
                    or (guild_settings.secondary_leaderboard_name != "" and for_who.lower().startswith(guild_settings.secondary_leaderboard_name.lower()))):
                await safe_send(message.channel, "Put a valid leaderboard type: " + ", ".join([guild_settings.primary_leaderboard_name, guild_settings.secondary_leaderboard_name]) + f"\n*Example: !{guild_settings.primary_rating_command} {guild_settings.primary_leaderboard_name} Jacob*", delete_after=10)
                return
        lookup = True
        is_primary_rating = True
        is_primary_leaderboard = True if not guild_settings.secondary_leaderboard_on else for_who.lower().startswith(guild_settings.primary_leaderboard_name.lower())
        title_end = (" - " + (guild_settings.primary_leaderboard_name if is_primary_leaderboard else guild_settings.secondary_leaderboard_name)) if guild_settings.secondary_leaderboard_on else ""
        strip_set = {guild_settings.primary_leaderboard_name.lower()}.union(set() if not guild_settings.secondary_leaderboard_on else {guild_settings.secondary_leaderboard_name.lower()})
        for_who = strip_prefix_and_command(for_who, strip_set, "") if guild_settings.secondary_leaderboard_on else for_who
    
    elif message.content.lower().startswith('!' + guild_settings.secondary_rating_command.lower()) or \
            (message.content.lower().startswith('^' + guild_settings.secondary_rating_command.lower()) and is_lounge(message.guild.id)):
        for_who = strip_prefix_and_command(message.content, {guild_settings.secondary_rating_command.lower()}, message.content[0])
        valid_types = []
        if guild_settings.primary_leaderboard_secondary_rating_on:
            valid_types.append(guild_settings.primary_leaderboard_name)
        if guild_settings.secondary_leaderboard_secondary_rating_on:
            valid_types.append(guild_settings.secondary_leaderboard_name)
        if len(valid_types) == 0:
            return
        if len(valid_types) > 1:
            for t in valid_types:
                if t != "" and for_who.lower().startswith(t.lower()):
                    for_who = strip_prefix_and_command(for_who, {t.lower()}, "")
                    is_primary_leaderboard = t == guild_settings.primary_leaderboard_name
                    title_end = " - " + (guild_settings.primary_leaderboard_name if is_primary_leaderboard else guild_settings.secondary_leaderboard_name)
                    break
            else:
                await safe_send(message.channel, "Put a valid leaderboard type: " + ", ".join(valid_types) + f"\n*Example: !{guild_settings.secondary_rating_command} {valid_types[0]} Jacob*", delete_after=10)
                return
        else:
            is_primary_leaderboard = guild_settings.primary_leaderboard_secondary_rating_on
        lookup = True
        is_primary_rating = False
    
        
    if lookup and is_primary_leaderboard is not None and is_primary_rating is not None:
        to_look_up = for_who.split(",")
        to_look_up = [name.strip() for name in to_look_up if len(name.strip()) > 0]
        if len(to_look_up) == 0: #get elo/rating for author
            to_look_up = [message.author.display_name]
        else: #they are trying to look someone, or multiple people up
            if len(to_look_up) > 15:
                await safe_send(message.channel, "A maximum of 15 players can be checked at a time.", delete_after=10)
                return
            for name in to_look_up:
                if len(name) > 25:
                    await safe_send(message.channel, "One of the names was too long. I'm not going to look this up.", delete_after=10)
                    return
                
        playerMMRs = await bot.get_cog('Elo').mmr(message.channel, to_look_up, is_primary_leaderboard, is_primary_rating)
        if playerMMRs is False:
            return
        title = guild_settings.rating_command_primary_rating_embed_title if is_primary_rating else guild_settings.rating_command_secondary_rating_embed_title
        if title != "":
            title += title_end
        embed = discord.Embed(
                                title = title,
                                colour = discord.Colour.dark_blue()
                            )            
        
        for name, rating in sorted(playerMMRs.items(), key=lambda data: -1 if data[1] is False else data[1], reverse=True):
            mmr_str = "Unknown" if rating is False else str(rating)
            embed.add_field(name=name, value=mmr_str, inline=False)
        
        if is_lounge(message.guild.id):
            await lounge_mmr_send_with_ranking_icon(message.channel, embed, guild_settings, is_primary_leaderboard, is_primary_rating)
        else:
            await safe_send(message.channel, embed=embed, delete_after=30)

lounge_folder_path = ''
lounge_runner_cutoff_filename = [(999, 'iron.png', "<:Iron:801548182415867954>"),
                          (1999, 'bronze.png', "<:Bronze:801548182298689546>"),
                          (3999, 'silver.png', "<:Silver:801548182286762096>"),
                          (5999, 'gold.png', "<:Gold:801548182747086868>"),
                          (7999, 'platinum.png', "<:Platinum:801548183372169256>"),
                          (9999, 'diamond.png', "<:Diamond:801548182319792168>"),
                          (9999999,'master.png', "<:Master:801548182416261120>")]
lounge_bagger_cutoff_filename = [(499, 'iron.png', "<:Iron:801548182415867954>"),
                          (999, 'bronze.png', "<:Bronze:801548182298689546>"),
                          (1999, 'silver.png', "<:Silver:801548182286762096>"),
                          (2999, 'gold.png', "<:Gold:801548182747086868>"),
                          (3999, 'platinum.png', "<:Platinum:801548183372169256>"),
                          (4999, 'diamond.png', "<:Diamond:801548182319792168>"),
                          (9999999,'master.png', "<:Master:801548182416261120>")]

def lounge_get_ranking_file_name(mmr:int, primary_rating=True):
    to_use = lounge_runner_cutoff_filename if primary_rating else lounge_bagger_cutoff_filename
    mmr_icon_data = (to_use[-1][1], to_use[-1][2])
    for cutoff, file_name_path, discord_emoji  in to_use[:-1]:
        if mmr <= cutoff:
            mmr_icon_data = (lounge_folder_path + file_name_path, discord_emoji)
            break
    return mmr_icon_data

async def loung_stats_send_with_ranking_icon(ctx, player_name, stats_data, embed_author_name, primary_rating):
    embed = discord.Embed(
                            title = player_name,
                            colour = discord.Colour.dark_blue()
                        )
    MMR_INDEX = 1
    
    embed.set_author(name=embed_author_name, url=embed.author.url, icon_url="https://mariokartboards.com/lounge/images/logo.png")
    
    file=None
    if stats_data[MMR_INDEX][1].isnumeric():
        file_path, _ = lounge_get_ranking_file_name(int(stats_data[MMR_INDEX][1]), primary_rating)
        file = discord.File(file_path)
        embed.set_thumbnail(url="attachment://" + file_path)
        
    for stat_name, stat_value in stats_data:
        embed.add_field(name="-" if len(str(stat_name).strip()) == 0 else str(stat_name), value="-" if len(str(stat_value).strip()) == 0 else str(stat_value))
    await ctx.send(file=file, embed=embed, delete_after=30)
        
    
async def lounge_mmr_send_with_ranking_icon(channel:discord.TextChannel, embed:discord.Embed, guild_settings, is_primary_leaderboard=True, primary_rating=True):
    embed.set_author(name="\u200b" + embed.title, url=embed.author.url, icon_url="https://mariokartboards.com/lounge/images/logo.png")
    embed.title = ""
    if len(embed.fields) == 1:
        #do one person
        embed.title = embed.fields[0].name
        file = None
        if not embed.fields[0].value.isnumeric():
            await safe_send(channel, f"Could not find {guild_settings.primary_leaderboard_name if is_primary_leaderboard else guild_settings.secondary_leaderboard_name} {guild_settings.primary_rating_command if primary_rating else guild_settings.secondary_rating_command} for the specified player.", delete_after=30)
            return
        
        file_path, _ = lounge_get_ranking_file_name(int(embed.fields[0].value), primary_rating)
        file = discord.File(file_path)
        embed.set_thumbnail(url="attachment://" + file_path)
        embed.description = embed.fields[0].value
        embed.clear_fields()
        await safe_send(channel, file=file, embed=embed, delete_after=30)
    else:
        missing_player_count = 0
        for index in reversed(range(len(embed.fields))):
            field = embed.fields[index]
            if field.value.isnumeric():
                _, discord_lounge_rating_icon = lounge_get_ranking_file_name(int(field.value), primary_rating)
                new_name = field.name + "  " + discord_lounge_rating_icon
                embed.set_field_at(index, name=new_name, value=field.value, inline=field.inline)
            else:
                missing_player_count += 1
                embed.remove_field(index)
        if missing_player_count > 0:
            embed.set_footer(text=f"Could not find {guild_settings.primary_leaderboard_name if is_primary_leaderboard else guild_settings.secondary_leaderboard_name} {guild_settings.primary_rating_command if primary_rating else guild_settings.secondary_rating_command} for {missing_player_count} of the players.")
                
            
        await safe_send(channel, embed=embed, delete_after=30)    
        
def setup(bot):
    bot.add_cog(Queue(bot))
    GuildSettings.setup(bot)
