import os
import requests

FACEBOOK_TOKEN = os.environ["FACEBOOK_TOKEN"]
FACEBOOK_PAGE_ID = os.environ["FACEBOOK_PAGE_ID"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
WP_URL = os.environ["WP_URL"].rstrip("/")
WP_USER = os.environ["WP_USER"]
WP_PASSWORD = os.environ["WP_PASSWORD"]

PROCESSED_FILE = "processed_ids.txt"

GEMINI_PROMPT = """Sos un redactor de prensa profesional. Transformá el siguiente texto de una publicación de Facebook en una gacetilla de prensa en español.

La gacetilla debe tener este formato exacto:
TÍTULO: (título llamativo en estilo periodístico)
COPETE: (una oración resumen)
CUERPO: (2 o 3 párrafos en tercera persona, estilo periodístico)
CIERRE: (datos de contacto si los hay en el texto, o una oración de cierre institucional)

Publicación de Facebook:
{post_text}"""


def load_processed_ids():
    if os.path.exists(PROCESSED_FILE):
        with open(PROCESSED_FILE, "r") as f:
            return set(line.strip() for line in f if line.strip())
    return set()


def save_processed_id(post_id):
    with open(PROCESSED_FILE, "a") as f:
        f.write(post_id + "\n")


def get_facebook_posts(limit=20):
    url = f"https://graph.facebook.com/v19.0/{FACEBOOK_PAGE_ID}/posts"
    params = {
        "fields": "id,message,story,created_time,full_picture,attachments{media,type,url}",
        "limit": limit,
        "access_token": FACEBOOK_TOKEN,
    }
    response = requests.get(url, params=params)
    if not response.ok:
        print(f"Error Facebook API: {response.status_code} - {response.text}")
    response.raise_for_status()
    posts = response.json().get("data", [])
    print(f"Posts obtenidos de Facebook: {len(posts)}")
    for p in posts:
        text = p.get("message") or p.get("story") or ""
        img = p.get("full_picture", "")
        print(f"  [{p.get('created_time','')[:10]}] texto: {repr(text[:60])} | imagen: {'SI' if img else 'NO'}")
    return posts


def generate_press_release(post_text):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {"contents": [{"parts": [{"text": GEMINI_PROMPT.format(post_text=post_text)}]}]}
    response = requests.post(url, json=payload)
    if not response.ok:
        print(f"Error Gemini: {response.status_code} - {response.text}")
    response.raise_for_status()
    return response.json()["candidates"][0]["content"]["parts"][0]["text"]


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
    return title or "Sin título", "\n".join(paragraphs)


def upload_image_to_wordpress(image_url):
    """Descarga la imagen de Facebook y la sube a WordPress. Retorna el media_id o None."""
    try:
        img_response = requests.get(image_url, timeout=15)
        img_response.raise_for_status()
        content_type = img_response.headers.get("Content-Type", "image/jpeg")
        ext = "jpg" if "jpeg" in content_type else content_type.split("/")[-1]
        filename = f"fb_image.{ext}"

        wp_media_url = f"{WP_URL}/wp-json/wp/v2/media"
        headers = {"Content-Disposition": f'attachment; filename="{filename}"', "Content-Type": content_type}
        resp = requests.post(
            wp_media_url,
            headers=headers,
            data=img_response.content,
            auth=(WP_USER, WP_PASSWORD),
        )
        if not resp.ok:
            print(f"Error subiendo imagen a WP: {resp.status_code} - {resp.text[:200]}")
            return None
        media = resp.json()
        print(f"Imagen subida a WordPress: {media.get('source_url', '')}")
        return media["id"], media.get("source_url", "")
    except Exception as e:
        print(f"No se pudo subir la imagen: {e}")
        return None


def publish_to_wordpress(title, content, featured_media_id=None):
    url = f"{WP_URL}/wp-json/wp/v2/posts"
    payload = {"title": title, "content": content, "status": "draft"}
    if featured_media_id:
        payload["featured_media"] = featured_media_id
    response = requests.post(url, json=payload, auth=(WP_USER, WP_PASSWORD))
    if not response.ok:
        print(f"Error WordPress: {response.status_code} - {response.text[:300]}")
    response.raise_for_status()
    return response.json().get("link", "sin link")


def collect_image_urls(post):
    """Recolecta todas las URLs de imágenes del post."""
    images = []
    # imagen principal
    if post.get("full_picture"):
        images.append(post["full_picture"])
    # imágenes adicionales de attachments
    attachments = post.get("attachments", {}).get("data", [])
    for att in attachments:
        media = att.get("media", {})
        img = media.get("image", {})
        url = img.get("src", "")
        if url and url not in images:
            images.append(url)
        # subattachments (álbumes)
        for sub in att.get("subattachments", {}).get("data", []):
            sub_url = sub.get("media", {}).get("image", {}).get("src", "")
            if sub_url and sub_url not in images:
                images.append(sub_url)
    return images


def main():
    print("=== Bot Gabriela Ortiz: Facebook → WordPress ===\n")
    processed_ids = load_processed_ids()
    print(f"Posts ya procesados: {len(processed_ids)}\n")

    posts = get_facebook_posts(limit=20)

    nuevos = [p for p in posts if p["id"] not in processed_ids]
    print(f"\nPosts nuevos a procesar: {len(nuevos)}")

    if not nuevos:
        print("No hay posts nuevos.")
        return

    # del más viejo al más nuevo
    for post in reversed(nuevos):
        post_id = post["id"]
        text = post.get("message") or post.get("story") or ""
        fecha = post.get("created_time", "")[:10]

        print(f"\n--- Procesando post {post_id} ({fecha}) ---")

        if not text:
            print("Sin texto, omitiendo.")
            save_processed_id(post_id)
            continue

        print(f"Texto: {text[:120]}...")

        # generar gacetilla
        print("Generando gacetilla con Gemini...")
        press_release = generate_press_release(text)
        title, body_html = parse_press_release(press_release)
        print(f"Título: {title}")

        # subir imágenes a WordPress
        image_urls = collect_image_urls(post)
        print(f"Imágenes encontradas: {len(image_urls)}")

        featured_media_id = None
        extra_images_html = ""

        for i, img_url in enumerate(image_urls):
            result = upload_image_to_wordpress(img_url)
            if result:
                media_id, source_url = result
                if i == 0:
                    featured_media_id = media_id
                extra_images_html += f'<figure><img src="{source_url}" /></figure>\n'

        # armar contenido final
        content = body_html
        if extra_images_html:
            content += "\n" + extra_images_html

        # publicar en WordPress
        print("Publicando en WordPress...")
        wp_link = publish_to_wordpress(title, content, featured_media_id)
        print(f"Borrador creado: {wp_link}")

        save_processed_id(post_id)

    print("\n=== Listo ===")


if __name__ == "__main__":
    main()
