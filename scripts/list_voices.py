import asyncio
import edge_tts

async def main():
    voices = await edge_tts.list_voices()
    hi_voices = [v for v in voices if 'hi-IN' in v['ShortName'] or 'Hindi' in v['FriendlyName'] or 'en-IN' in v['ShortName']]
    for v in hi_voices:
        print(f"{v['ShortName']} | {v['Gender']} | {v['FriendlyName']}")

asyncio.run(main())
