import asyncio
from random import randint
from PIL import Image
import requests
from dotenv import get_key, load_dotenv # Use load_dotenv to load the .env file
import os
from time import sleep
import base64 # Needed for Stability AI
import json # Needed to handle potential errors

# --- Load environment variables from .env file ---
load_dotenv()

# --- Functions for opening images (No Change) ---
def open_images(prompt):
    folder_path = r"Data"
    prompt = prompt.replace(" ", "_")
    # We will save as PNG for Stability AI
    Files = [f"{prompt}{i}.png" for i in range(1, 2)]

    for file in Files:
        image_path = os.path.join(folder_path, file)
        try:
            img = Image.open(image_path)
            print(f"Opening image: {image_path}")
            img.show()
            sleep(1)
        except IOError:
            print(f"Unable to open {image_path}. The file might not have been generated due to an error.")

# --- NEW FUNCTIONS FOR STABILITY AI ---

# Stability AI API configuration
STABILITY_API_URL = "https://api.stability.ai/v1/generation/stable-diffusion-v1-6/text-to-image"
STABILITY_API_KEY = get_key('.env', 'StabilityAI_APIKey')

# Check if the Stability AI API key exists
if not STABILITY_API_KEY:
    raise ValueError("StabilityAI_APIKey not found in .env file. Please add it.")

# Headers for the Stability AI API
stability_headers = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Authorization": f"Bearer {STABILITY_API_KEY}",
}

async def generate_single_image_stability(prompt: str, image_number: int):
    """Generates a single image using the Stability AI API and saves it."""
    
    # Payload for the Stability AI API
    payload = {
        "text_prompts": [{"text": f"{prompt}, 4k, high-resolution, photorealistic"}],
        "cfg_scale": 7,
        "height": 1024,
        "width": 1024,
        "samples": 1,
        "steps": 30,
        "seed": randint(0, 4294967295) # Stability uses a larger seed range
    }

    print(f"Requesting image {image_number} from Stability AI...")
    
    # Asynchronous request
    response = await asyncio.to_thread(
        requests.post,
        STABILITY_API_URL,
        headers=stability_headers,
        json=payload
    )

    if response.status_code != 200:
        print(f"Error for image {image_number}: {response.status_code} - {response.text}")
        return

    response_data = response.json()

    # Save the received image
    for i, image in enumerate(response_data.get("artifacts", [])):
        file_path = fr"Data\{prompt.replace(' ', '_')}{image_number}.png" # Save as PNG
        print(f"Saving image to {file_path}")
        with open(file_path, "wb") as f:
            f.write(base64.b64decode(image["base64"]))

async def generate_images_stability(prompt: str):
    """Creates and runs tasks to generate 4 images concurrently."""
    tasks = []
    for i in range(1, 2): # Generate images 1, 2, 3, 4
        task = asyncio.create_task(generate_single_image_stability(prompt, i))
        tasks.append(task)
    
    await asyncio.gather(*tasks)

def GenerateImages(prompt: str):
    # This function now calls the new Stability AI functions
    asyncio.run(generate_images_stability(prompt))
    open_images(prompt)

# --- Main execution loop (No Change) ---
while True:
    try:
        with open(r"Frontend\Files\ImageGeneration.data", "r") as f:
            Data: str = f.read()

        Prompt, Status = Data.split(",")

        if Status == "True":
            print("Generating Images using Stability AI...")
            GenerateImages(prompt=Prompt)

            with open(r"Frontend\Files\ImageGeneration.data", "w") as f:
                f.write("False, False")
            break
        else:
            sleep(1)
    except FileNotFoundError:
        print("Waiting for ImageGeneration.data file...")
        sleep(1)
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        with open(r"Frontend\Files\ImageGeneration.data", "w") as f:
            f.write("False, False")
        break