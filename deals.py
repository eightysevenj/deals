import discord
from discord.ext import commands
import requests
import asyncio
import logging
from bs4 import BeautifulSoup
import os

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('discord_bot')

# URLs for the APIs
deal_activity_url = "https://api.rolimons.com/market/v1/dealactivity"
item_details_url = "https://api.rolimons.com/items/v1/itemdetails"

# Function to fetch item image URL from Adurite
def fetch_item_image_url(item_id):
    try:
        # Using adurite.com to fetch the item thumbnail
        url = f"https://images.adurite.com/images?assetId={item_id}&width=150&height=150&format=Png"
        
        # Use requests to follow redirects and get the final URL
        response = requests.head(url, allow_redirects=True)
        final_url = response.url
        
        return final_url
    except Exception as e:
        logger.error(f"Error fetching image URL for asset ID {item_id}: {e}")
        return None

# Function to check if an item is sold on Roblox
def is_item_sold(item_id):
    try:
        # Example URL to check item status on Roblox
        item_url = f"https://www.roblox.com/catalog/{item_id}/"
        response = requests.get(item_url)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Find the price element
        price_element = soup.find('span', class_='text-robux-lg')
        if price_element:
            current_price = int(price_element.text.replace(',', ''))
            
            # You can set a threshold for what constitutes as "sold"
            original_price = 3600  # Example original price
            if current_price > original_price:
                return False
            else:
                return True
        else:
            logger.error(f"Price element not found for item ID {item_id}")
            return False
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching item webpage for asset ID {item_id}: {e}")
        return False
    except Exception as e:
        logger.error(f"Error parsing item webpage for asset ID {item_id}: {e}")
        return False

# Fetch data from the deal activity API
def fetch_deal_activity():
    try:
        response = requests.get(deal_activity_url)
        response.raise_for_status()
        data = response.json()
        logger.info("Fetched deal activity data successfully.")
        return data['activities']
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching deal activity: {e}")
        return None

# Fetch item details from the item details API
def fetch_item_details():
    try:
        response = requests.get(item_details_url)
        response.raise_for_status()
        data = response.json()
        logger.info("Fetched item details data successfully.")
        return data['items']
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching item details: {e}")
        return None

# Filter deals with a discount of 10% or more
def filter_deals(activities, items, price_min=None, price_max=None, item_types=None):
    deals = []
    for activity in activities:
        item_id = str(activity[2])
        if item_id in items:
            item_name = items[item_id][0]
            item_rap = items[item_id][2]
            item_value = items[item_id][4] if items[item_id][4] != -1 else item_rap
            item_price = activity[3]

            discount = ((item_value - item_price) / item_value) * 100
            if discount >= 10:
                if (price_min is not None and item_price < price_min) or (price_max is not None and item_price > price_max):
                    continue
                if item_types and items[item_id][1] not in item_types:
                    continue

                deals.append({
                    'id': item_id,
                    'name': item_name,
                    'value': item_value,
                    'rap': item_rap,
                    'price': item_price,
                    'discount': discount
                })
    return deals

# Sort deals by a specified key
def sort_deals(deals, sort_key):
    return sorted(deals, key=lambda x: x[sort_key], reverse=True)

# Define the bot
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Your bot token and role ID
TOKEN = os.getenv('DISCORD_BOT_TOKEN')
CHANNEL_ID = 1254916635760787530  # Replace with your channel ID
ROLE_ID = 1254916788546703460  # Replace with the role ID you want to mention

# Dictionary to store message IDs of posted deals and their sold status
posted_deals = {}

async def fetch_and_post_deals(ctx=None, sort_key=None, min_discount=10, price_min=None, price_max=None, item_types=None):
    channel = bot.get_channel(CHANNEL_ID)
    
    if channel is None:
        logger.error(f"Channel with ID {CHANNEL_ID} not found.")
        return

    role_mention = f"<@&{ROLE_ID}>"
    
    logger.info("Fetching deal activities...")
    activities = fetch_deal_activity()
    if not activities:
        logger.warning("Failed to fetch deal activities.")
        await asyncio.sleep(30)  # Retry in 30 seconds
        return

    logger.info("Fetching item details...")
    items = fetch_item_details()
    if not items:
        logger.warning("Failed to fetch item details.")
        await asyncio.sleep(30)  # Retry in 30 seconds
        return

    logger.info("Filtering deals with 10% or more discount...")
    deals = filter_deals(activities, items, price_min, price_max, item_types)
    if not deals:
        logger.info("No deals found with 10% or more discount. Retrying in 30 seconds...")
        await asyncio.sleep(30)  # Retry in 30 seconds
        return

    if sort_key:
        deals = sort_deals(deals, sort_key)

    # Create a list of current deal IDs
    current_deal_ids = [deal['id'] for deal in deals]

    # Check for removed deals and update Discord
    removed_deal_ids = []
    for deal_id, message_id in posted_deals.items():
        if deal_id not in current_deal_ids:
            try:
                message = await channel.fetch_message(message_id)
                embed = message.embeds[0]
                embed.title = f"❌ SOLD: {embed.title.split('SOLD: ')[-1]}"
                embed.color = discord.Color.red()
                await message.edit(embed=embed)
                logger.info(f"Updated deal: {deal_id} as SOLD in Discord.")
            except discord.NotFound:
                logger.warning(f"Message for deal {deal_id} not found.")
            except discord.DiscordException as e:
                logger.error(f"Error updating message for deal {deal_id}: {e}")
            removed_deal_ids.append(deal_id)

    # Remove deleted deals from the dictionary
    for deal_id in removed_deal_ids:
        del posted_deals[deal_id]

    # Post new deals to Discord
    for deal in deals:
        discount = deal['discount']
        if discount >= 30:
            color = discord.Color.purple()
        elif discount >= 20:
            color = discord.Color.green()
        elif discount >= 10:
            color = discord.Color.dark_gray()  # Using dark gray for 10% discount
        else:
            color = discord.Color.default()

        item_link = f"https://www.roblox.com/catalog/{deal['id']}/{deal['name'].replace(' ', '-')}"
        image_url = fetch_item_image_url(deal['id'])
        
        if not image_url:
            continue  # Skip this deal if image URL fetch failed
        
        # Check if the item is sold
        is_sold = is_item_sold(deal['id'])
        
        # Determine the title based on item availability
        if is_sold:
            sold_title = f"❌ SOLD: {deal['name']}"
        else:
            sold_title = f"🔥 Deal Found: {deal['name']}"
        
        # Create the embed
        embed = discord.Embed(
            title=sold_title,
            description=f"**Value:** {deal['value']:,}\n"
                        f"**RAP:** {deal['rap']:,}\n"
                        f"**Price:** {deal['price']:,}\n"
                        f"**Discount:** {discount:.2f}% off",
            color=color
        )
        embed.set_thumbnail(url=image_url)
        
        # Add a line separator
        embed.add_field(name="\u200b", value="\u200b", inline=False)

        # Add a clickable link as an inline field
        embed.add_field(
            name="View on Roblox",
            value=f"[Click here to view {deal['name']} on Roblox]({item_link})",
            inline=False
        )

        try:
            if deal['id'] in posted_deals:
                message = await channel.fetch_message(posted_deals[deal['id']])
                await message.edit(embed=embed)
                logger.info(f"Updated deal: {deal['name']} with {discount:.2f}% discount")
            else:
                sent_message = await channel.send(content=role_mention, embed=embed)
                posted_deals[deal['id']] = sent_message.id
                logger.info(f"Posted new deal: {deal['name']} with {discount:.2f}% discount")
        except discord.DiscordException as e:
            logger.error(f"Error sending/updating message to Discord for deal {deal['name']}: {e}")

# Periodically fetch and post deals
async def periodic_fetch_and_post_deals():
    while True:
        await fetch_and_post_deals()
        await asyncio.sleep(30)  # Wait for 30 seconds before fetching again

# Command to sort by discount
@bot.command(name='sort_discount')
async def sort_by_discount(ctx):
    await fetch_and_post_deals(ctx, sort_key='discount')

# Command to sort by item value
@bot.command(name='sort_value')
async def sort_by_value(ctx):
    await fetch_and_post_deals(ctx, sort_key='value')

# Command to filter by price range
@bot.command(name='filter_price')
async def filter_by_price(ctx, price_min: int, price_max: int):
    await fetch_and_post_deals(ctx, price_min=price_min, price_max=price_max)

# Command to filter by item type
@bot.command(name='filter_type')
async def filter_by_type(ctx, *item_types):
    await fetch_and_post_deals(ctx, item_types=item_types)

# Bot event on ready
@bot.event
async def on_ready():
    logger.info(f'Logged in as {bot.user.name} - {bot.user.id}')
    logger.info('Bot is ready to fetch and post deals.')

    # Start the periodic task
    bot.loop.create_task(periodic_fetch_and_post_deals())

# Run the bot
if __name__ == "__main__":
    bot.run(TOKEN)
