import os
import requests

FACEBOOK_TOKEN = os.environ["FACEBOOK_TOKEN"]
FACEBOOK_PAGE_ID = os.environ["FACEBOOK_PAGE_ID"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
WP_URL = os.environ["WP_URL"]
WP_USER = os.environ["WP_USER"]
WP_PASSWORD = os.environ["WP_PASSWORD"]

LAST_POST_FILE = "last_post.txt"

GEMINI_PROMPT = """Sos un redactor de prensa profesional. Transformá el siguiente texto de una publicación de Facebook en una gacetilla de prensa en español.

La gacetilla debe tener este formato exacto:
TÍTULO: (título llamativo en estilo periodístico)
COPETE: (una oración resumen)
CUERPO: (2 o 3 párrafos en tercera persona, estilo periodístico)
CIERRE: (datos de contacto si los hay en el texto, o una oración de cierre institucional)

Publicación de Facebook:
{post_text}"""


def get_last_processed_id():
    if os.path.exists(LAST_POST_FILE):
        with open(LAST_POST_FILE, "r") as f:
            return f.read().strip()
    return None


def save_last_processed_id(post_id):
    with open(LAST_POST_FILE, "w") as f:
        f.write(post_id)


def get_facebook_posts(limit=20):
    url = f"https://graph.facebook.com/v19.0/{FACEBOOK_PAGE_ID}/posts"
    params = {
        "fields": "id,message,story,created_time",
        "limit": limit,
        "access_token": FACEBOOK_TOKEN,
    }
    response = requests.get(url, params=params)
    if not response.ok:
        print(f"Error Facebook API: {response.status_code}")
        print(f"Respuesta: {response.text}")
    response.raise_for_status()
    data = response.json()
    posts = data.get("data", [])
    print(f"Posts obtenidos de Facebook: {len(posts)}")
    for p in posts:
        msg = p.get("message", "")
        story = p.get("story", "")
        print(f"  - {p.get('created_time', '')[:10]} | message: {repr(msg[:60])} | story: {repr(story[:60])}")
    return posts


def generate_press_release(post_text):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": GEMINI_PROMPT.format(post_text=post_text)}]}]
    }
    response = requests.post(url, json=payload)
    if not response.ok:
        print(f"Error Gemini API: {response.status_code} - {response.text}")
    response.raise_for_status()
    result = response.json()
    return result["candidates"][0]["content"]["parts"][0]["text"]


def parse_press_release(text):
    title = ""
    body_lines = []
    for line in text.split("\n"):
        if line.startswith("TÍTULO:"):
            title = line.replace("TÍTULO:", "").strip()
        else:
            body_lines.append(line)
    body = "\n".join(body_lines).strip()
    paragraphs = [f"<p>{p.strip()}</p>" for p in body.split("\n\n") if p.strip()]
    return title, "\n".join(paragraphs)


def publish_to_wordpress(title, content):
    url = f"{WP_URL}/wp-json/wp/v2/posts"
    payload = {
        "title": title,
        "content": content,
        "status": "draft",
    }
    response = requests.post(url, json=payload, auth=(WP_USER, WP_PASSWORD))
    if not response.ok:
        print(f"Error WordPress API: {response.status_code} - {response.text}")
    response.raise_for_status()
    return response.json().get("link", "sin link")


def main():
    print("Buscando posts en Facebook...")
    posts = get_facebook_posts(limit=20)
    last_id = get_last_processed_id()
    print(f"Último post procesado: {last_id}")

    nuevos = []
    for post in posts:
        if post["id"] == last_id:
            break
        text = post.get("message") or post.get("story")
        if text:
            post["_text"] = text
            nuevos.append(post)

    if not nuevos:
        print("No hay posts nuevos con texto.")
        return

    print(f"Posts nuevos a procesar: {len(nuevos)}")

    # procesa del más viejo al más nuevo
    for post in reversed(nuevos):
        print(f"\nProcesando post: {post['id']} ({post.get('created_time', '')[:10]})")
        print(f"Texto: {post['_text'][:100]}...")

        print("Generando gacetilla con Gemini...")
        press_release = generate_press_release(post["_text"])

        title, content = parse_press_release(press_release)
        print(f"Título generado: {title}")

        print("Publicando en WordPress...")
        wp_link = publish_to_wordpress(title, content)
        print(f"Borrador creado: {wp_link}")

        save_last_processed_id(post["id"])

    print("\nListo.")


if __name__ == "__main__":
    main()
