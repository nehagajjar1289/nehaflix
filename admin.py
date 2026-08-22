"""
admin.py — NehaFlix Admin / Content Management Panel
======================================================
A self-contained Streamlit module that adds a professional admin
dashboard to the existing NehaFlix OTT project.

This file is designed to be imported and called from app.py:

    from admin import admin_page
    ...
    if st.session_state.get("show_admin"):
        admin_page()
        st.stop()

It does NOT touch the user-facing app logic, does NOT rewrite
movies.csv's schema, and does NOT modify users.db / reviews.json /
parties.json beyond what is explicitly described below:

    - movies.csv  -> read AND written (this is the whole point of the panel)
    - users.json  -> read only (never modified)
    - reviews.json -> read only (never modified)
    - parties.json -> read only, only for a dashboard count (never modified)
    - users.db    -> read only (never modified). NOTE: app.py does not
                     actually use users.db anywhere — it only contains a
                     leftover "likes" table (username, movie) from an
                     earlier iteration of the project. We surface it as a
                     bonus stat, but real "Total Users" comes from users.json.

Schema used (exactly matches the existing movies.csv — nothing invented):
    movie_id, title, genre, rating, poster, trailer
"""

import streamlit as st
import pandas as pd
import sqlite3
import json
import re
from pathlib import Path
from datetime import datetime

# ────────────────────────────────────────────────
# PATHS — mirrors app.py exactly, same folder
# ────────────────────────────────────────────────
DATA_DIR      = Path(".")
MOVIES_FILE   = DATA_DIR / "movies.csv"
POSTER_DIR    = DATA_DIR / "poster"
USERS_FILE    = DATA_DIR / "users.json"
REVIEWS_FILE  = DATA_DIR / "reviews.json"
PARTIES_FILE  = DATA_DIR / "parties.json"
DB_FILE       = DATA_DIR / "users.db"
POSTER_DIR.mkdir(exist_ok=True)

MOVIE_COLUMNS = ["movie_id", "title", "genre", "rating", "poster", "trailer"]

# Fallback admin credentials — ONLY used if .streamlit/secrets.toml is not
# configured. These are intentionally never printed/rendered anywhere in
# the UI. Change them, or (much better) set up secrets.toml — see the
# warning banner shown in the login screen when this fallback is active.
_FALLBACK_ADMIN_USER = "admin"
_FALLBACK_ADMIN_PASS = "ChangeThisPassword123"


# ══════════════════════════════════════════════════════════
# STYLING
# ══════════════════════════════════════════════════════════
def _inject_admin_css():
    """
    Adds a handful of admin-only CSS classes. Deliberately does NOT
    redefine .hero-banner / .stat-card / .section-title / .movie-card /
    .neon-divider / .sidebar-logo — those are already injected by app.py
    (admin_page() is only ever called from inside app.py, after that CSS
    block has already run), so we simply reuse them for visual consistency.
    """
    st.markdown("""
    <style>
    .admin-login-wrap {
        max-width: 420px; margin: 40px auto 0; padding: 32px 30px;
        background: linear-gradient(135deg,#0a1830 0%,#0d2040 100%);
        border: 1.5px solid #00e5ff44; border-radius: 18px;
        box-shadow: 0 0 30px #00e5ff22;
        animation: heroFade .5s ease forwards;
    }
    .admin-login-title {
        font-size: 22px; font-weight: 800; color: #00e5ff;
        text-shadow: 0 0 16px #00e5ff88; text-align:center; margin-bottom: 4px;
    }
    .admin-login-sub { text-align:center; color:#8899bb; font-size:12px; margin-bottom: 20px; }
    .admin-warning-box {
        background:#2a1a0d; border:1.5px solid #ffaa0055; border-radius:10px;
        padding:10px 14px; font-size:11.5px; color:#ffcc88; margin-bottom:16px;
    }
    .admin-badge-role {
        display:inline-block; background:linear-gradient(135deg,#7c3aed,#4f46e5);
        color:#fff; border-radius:8px; padding:3px 12px; font-size:11px;
        font-weight:700; box-shadow:0 0 10px #7c3aed66;
    }
    .admin-danger-box {
        background:#2a0d0d; border:1.5px solid #ff4d4d55; border-radius:12px;
        padding:16px 18px; margin:14px 0;
    }
    .admin-info-row {
        display:flex; justify-content:space-between; padding:6px 0;
        border-bottom:1px solid #1a3060; font-size:13px;
    }
    .admin-info-row b { color:#00e5ff; }
    </style>
    """, unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════
# MOVIES.CSV — LOAD / SAVE / CRUD  (error-handled throughout)
# ══════════════════════════════════════════════════════════
def load_movies():
    """Load movies.csv defensively. Never crashes the app."""
    try:
        if not MOVIES_FILE.exists():
            st.warning("⚠️ movies.csv was not found. Starting with an empty movie list — "
                       "adding a movie below will create the file.")
            return pd.DataFrame(columns=MOVIE_COLUMNS)

        df = pd.read_csv(MOVIES_FILE)

        if df.empty:
            return pd.DataFrame(columns=MOVIE_COLUMNS)

        # Defensive: make sure all expected columns exist (in case of a
        # partially edited CSV) without inventing new schema fields.
        for col in MOVIE_COLUMNS:
            if col not in df.columns:
                df[col] = "" if col not in ("movie_id", "rating") else 0

        return df[MOVIE_COLUMNS]

    except pd.errors.EmptyDataError:
        return pd.DataFrame(columns=MOVIE_COLUMNS)
    except Exception as e:
        st.error(f"❌ Could not read movies.csv: {e}")
        return pd.DataFrame(columns=MOVIE_COLUMNS)


def save_movies(df):
    """Write movies.csv defensively. Returns True/False."""
    try:
        out = df[MOVIE_COLUMNS].copy()
        out["movie_id"] = pd.to_numeric(out["movie_id"], errors="coerce").fillna(0).astype(int)
        out.to_csv(MOVIES_FILE, index=False)
        return True
    except PermissionError:
        st.error("❌ Permission denied while writing movies.csv. "
                 "Check the file isn't read-only or open elsewhere.")
        return False
    except Exception as e:
        st.error(f"❌ Failed to save movies.csv: {e}")
        return False


def next_movie_id(df):
    if df.empty:
        return 1
    ids = pd.to_numeric(df["movie_id"], errors="coerce").fillna(0)
    return int(ids.max()) + 1


def title_exists(df, title, exclude_id=None):
    if df.empty or not title:
        return False
    mask = df["title"].astype(str).str.strip().str.lower() == title.strip().lower()
    if exclude_id is not None:
        mask &= df["movie_id"] != exclude_id
    return bool(mask.any())


def add_movie(df, title, genre, rating, poster_filename, trailer_url):
    """Validates + appends a new row. Returns (success: bool, message: str)."""
    title = (title or "").strip()
    genre = (genre or "").strip()
    trailer_url = (trailer_url or "").strip()

    if not title:
        return False, "Title is required."
    if not genre:
        return False, "Genre is required."
    if not trailer_url:
        return False, "Trailer URL is required."
    if not re.match(r"^https?://", trailer_url):
        return False, "Trailer URL must start with http:// or https://"
    if title_exists(df, title):
        return False, f"A movie titled '{title}' already exists — pick a different title or edit the existing one."

    new_row = {
        "movie_id": next_movie_id(df),
        "title": title,
        "genre": genre,
        "rating": float(rating),
        "poster": poster_filename or "",
        "trailer": trailer_url,
    }
    new_df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    if save_movies(new_df):
        return True, f"'{title}' was added successfully."
    return False, "Could not save the new movie — see error above."


def update_movie(df, movie_id, title, genre, rating, poster_filename, trailer_url):
    title = (title or "").strip()
    genre = (genre or "").strip()
    trailer_url = (trailer_url or "").strip()

    if not title:
        return False, "Title is required."
    if not genre:
        return False, "Genre is required."
    if not trailer_url:
        return False, "Trailer URL is required."
    if not re.match(r"^https?://", trailer_url):
        return False, "Trailer URL must start with http:// or https://"
    if title_exists(df, title, exclude_id=movie_id):
        return False, f"Another movie is already titled '{title}'. Choose a different title."

    idx = df.index[df["movie_id"] == movie_id]
    if len(idx) == 0:
        return False, "Movie not found (it may have been deleted already)."

    i = idx[0]
    df.loc[i, "title"] = title
    df.loc[i, "genre"] = genre
    df.loc[i, "rating"] = float(rating)
    df.loc[i, "poster"] = poster_filename or ""
    df.loc[i, "trailer"] = trailer_url

    if save_movies(df):
        return True, f"'{title}' was updated successfully."
    return False, "Could not save changes — see error above."


def delete_movie(df, movie_id):
    idx = df.index[df["movie_id"] == movie_id]
    if len(idx) == 0:
        return False, "Movie not found (it may have been deleted already)."
    title = df.loc[idx[0], "title"]
    new_df = df.drop(idx)
    if save_movies(new_df):
        return True, f"'{title}' was deleted successfully."
    return False, "Could not save after deletion — see error above."


def save_uploaded_poster(uploaded_file, allow_overwrite=False):
    """
    Saves an uploaded poster file into poster/ and returns the filename
    to store in movies.csv (matches existing get_poster_b64() logic in
    app.py, which reads POSTER_DIR / filename directly).
    """
    try:
        POSTER_DIR.mkdir(exist_ok=True)
        name = uploaded_file.name
        target = POSTER_DIR / name

        if target.exists() and not allow_overwrite:
            stem, ext = target.stem, target.suffix
            counter = 1
            while target.exists():
                target = POSTER_DIR / f"{stem}_{counter}{ext}"
                counter += 1

        with open(target, "wb") as f:
            f.write(uploaded_file.getbuffer())
        return target.name
    except PermissionError:
        st.error("❌ Permission denied while saving the poster image.")
        return None
    except Exception as e:
        st.error(f"❌ Failed to save poster: {e}")
        return None


# ══════════════════════════════════════════════════════════
# READ-ONLY HELPERS — users.json / reviews.json / parties.json / users.db
# ══════════════════════════════════════════════════════════
def load_users_readonly():
    try:
        if not USERS_FILE.exists():
            return {}
        with open(USERS_FILE) as f:
            raw = json.load(f)
        # users.json has a legacy top-level "users" key holding a list
        # (unused by app.py's actual login logic) alongside real accounts
        # stored as {username: {...}}. Only count real dict-shaped accounts.
        return {k: v for k, v in raw.items() if isinstance(v, dict)}
    except Exception as e:
        st.warning(f"⚠️ Could not read users.json: {e}")
        return {}


def load_reviews_readonly():
    try:
        if not REVIEWS_FILE.exists():
            return {}
        with open(REVIEWS_FILE) as f:
            return json.load(f)
    except Exception as e:
        st.warning(f"⚠️ Could not read reviews.json: {e}")
        return {}


def load_parties_readonly():
    try:
        if not PARTIES_FILE.exists():
            return {}
        with open(PARTIES_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def load_likes_count_readonly():
    """
    users.db contains a leftover 'likes' table (username, movie) that
    app.py currently does not read or write anywhere. We surface its row
    count here purely as an informational bonus stat — never modified.
    """
    try:
        if not DB_FILE.exists():
            return None
        conn = sqlite3.connect(str(DB_FILE))
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='likes'")
        if not cur.fetchone():
            conn.close()
            return None
        cur.execute("SELECT COUNT(*) FROM likes")
        count = cur.fetchone()[0]
        conn.close()
        return count
    except Exception:
        return None


# ══════════════════════════════════════════════════════════
# AUTH
# ══════════════════════════════════════════════════════════
def _get_admin_credentials():
    """Returns (username, password, using_fallback: bool)."""
    try:
        u = st.secrets["admin"]["username"]
        p = st.secrets["admin"]["password"]
        return u, p, False
    except Exception:
        return _FALLBACK_ADMIN_USER, _FALLBACK_ADMIN_PASS, True


def check_admin_credentials(entered_user, entered_pass):
    su, sp, using_fallback = _get_admin_credentials()
    return (entered_user == su and entered_pass == sp), using_fallback


def admin_login():
    _, _, using_fallback = _get_admin_credentials()

    st.markdown('<div class="admin-login-wrap">', unsafe_allow_html=True)
    st.markdown('<div class="admin-login-title">🛠️ NehaFlix Admin</div>', unsafe_allow_html=True)
    st.markdown('<div class="admin-login-sub">Content Management System</div>', unsafe_allow_html=True)

    if using_fallback:
        st.markdown("""
        <div class="admin-warning-box">
            ⚠️ No <code>.streamlit/secrets.toml</code> found — using a fallback
            admin login. For production use, set up secrets.toml
            (see the setup instructions provided with this panel) and this
            fallback will stop being used automatically.
        </div>""", unsafe_allow_html=True)

    with st.form("admin_login_form", clear_on_submit=False):
        u = st.text_input("Admin Username")
        p = st.text_input("Admin Password", type="password")
        submitted = st.form_submit_button("🔓 Login", type="primary", width='stretch')

    if submitted:
        ok, _ = check_admin_credentials(u, p)
        if ok:
            st.session_state.admin_logged_in = True
            st.rerun()
        else:
            st.error("Invalid admin credentials.")

    if st.button("← Back to NehaFlix"):
        st.session_state.show_admin = False
        st.rerun()

    st.markdown('</div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════
# DASHBOARD
# ══════════════════════════════════════════════════════════
def show_dashboard(movies_df, users, reviews, parties, likes_count):
    st.markdown('<div class="section-title">📊 Overview</div>', unsafe_allow_html=True)

    total_movies  = len(movies_df)
    total_genres  = movies_df["genre"].nunique() if not movies_df.empty else 0
    total_reviews = sum(len(v) for v in reviews.values()) if reviews else 0
    total_users   = len(users)
    total_trailers = movies_df["trailer"].astype(str).str.strip().replace("nan", "").ne("").sum() if not movies_df.empty else 0

    cols = st.columns(5)
    for col, (num, label) in zip(cols, [
        (str(total_movies), "Total Movies"),
        (str(total_genres), "Total Genres"),
        (str(total_reviews), "Total Reviews"),
        (str(total_users), "Total Users"),
        (str(total_trailers), "Total Trailers"),
    ]):
        col.markdown(f'<div class="stat-card"><div class="stat-number">{num}</div>'
                     f'<div class="stat-label">{label}</div></div>', unsafe_allow_html=True)

    st.markdown('<div class="neon-divider"></div>', unsafe_allow_html=True)

    c1, c2 = st.columns(2)
    with c1:
        st.markdown('<div class="section-title">🎭 Movies by Genre</div>', unsafe_allow_html=True)
        if not movies_df.empty:
            st.bar_chart(movies_df["genre"].value_counts())
        else:
            st.caption("No movies yet.")

    with c2:
        st.markdown('<div class="section-title">🎉 Active Watch Parties</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="stat-card"><div class="stat-number">{len(parties)}</div>'
                     f'<div class="stat-label">Live Parties</div></div>', unsafe_allow_html=True)
        if likes_count is not None:
            st.caption(f"ℹ️ users.db also has a legacy 'likes' table with **{likes_count}** row(s) — "
                       "not currently wired into the app, shown here for reference only.")

    st.markdown('<div class="neon-divider"></div>', unsafe_allow_html=True)
    st.markdown('<div class="section-title">🕓 Recently Added Movies</div>', unsafe_allow_html=True)
    if not movies_df.empty:
        st.dataframe(
            movies_df.sort_values("movie_id", ascending=False).head(5)[["movie_id", "title", "genre", "rating"]],
            width='stretch', hide_index=True,
        )
    else:
        st.caption("No movies yet — add one from the sidebar.")


# ══════════════════════════════════════════════════════════
# MOVIES — SEARCH / FILTER / LIST
# ══════════════════════════════════════════════════════════
def show_movie_list(movies_df):
    st.markdown('<div class="section-title">🎬 All Movies</div>', unsafe_allow_html=True)

    if movies_df.empty:
        st.info("No movies in movies.csv yet. Use ➕ Add Movie in the sidebar.")
        return

    c1, c2 = st.columns([2, 1])
    with c1:
        search_q = st.text_input("🔍 Search by title", placeholder="e.g. Dangal")
    with c2:
        genre_options = ["All"] + sorted(movies_df["genre"].dropna().unique().tolist())
        genre_filter = st.selectbox("Filter by genre", genre_options)

    filtered = movies_df.copy()
    if search_q.strip():
        filtered = filtered[filtered["title"].astype(str).str.lower().str.contains(search_q.strip().lower())]
    if genre_filter != "All":
        filtered = filtered[filtered["genre"] == genre_filter]

    st.caption(f"{len(filtered)} of {len(movies_df)} movies shown "
              "(only title/genre filters are offered — movies.csv has no year or language column).")
    st.dataframe(filtered[MOVIE_COLUMNS], width='stretch', hide_index=True)


# ══════════════════════════════════════════════════════════
# ADD MOVIE
# ══════════════════════════════════════════════════════════
def show_add_movie(movies_df):
    st.markdown('<div class="section-title">➕ Add New Movie</div>', unsafe_allow_html=True)

    existing_genres = sorted(movies_df["genre"].dropna().unique().tolist()) if not movies_df.empty else []

    title = st.text_input("Movie Title *")

    genre_choice = st.selectbox("Genre *", existing_genres + ["+ Add a new genre"] if existing_genres else ["+ Add a new genre"])
    if genre_choice == "+ Add a new genre":
        genre = st.text_input("New genre name *")
    else:
        genre = genre_choice

    rating = st.number_input("IMDb-style Rating *", min_value=0.0, max_value=10.0, value=7.5, step=0.1, format="%.1f")

    st.markdown("**Poster** (optional — falls back to a genre emoji if left blank, same as the rest of the app)")
    poster_file = st.file_uploader("Upload poster image", type=["png", "jpg", "jpeg"], key="add_poster_upload")
    poster_filename_manual = st.text_input(
        "...or type an existing filename already in poster/",
        placeholder="e.g. Master.png",
    )

    trailer_url = st.text_input("Trailer URL * (YouTube link, same format as the rest of movies.csv)",
                                placeholder="https://www.youtube.com/watch?v=...")

    if st.button("✅ Add Movie", type="primary"):
        poster_filename = ""
        if poster_file is not None:
            saved = save_uploaded_poster(poster_file, allow_overwrite=False)
            if saved:
                poster_filename = saved
        elif poster_filename_manual.strip():
            candidate = poster_filename_manual.strip()
            if (POSTER_DIR / candidate).exists():
                poster_filename = candidate
            else:
                st.warning(f"⚠️ '{candidate}' was not found in poster/ — the movie will still be "
                          "added, but its poster will show as a genre emoji until you upload one.")
                poster_filename = candidate

        ok, msg = add_movie(movies_df, title, genre, rating, poster_filename, trailer_url)
        if ok:
            st.success(f"✅ {msg}")
            st.rerun()
        else:
            st.error(f"❌ {msg}")


# ══════════════════════════════════════════════════════════
# EDIT MOVIE
# ══════════════════════════════════════════════════════════
def show_edit_movie(movies_df):
    st.markdown('<div class="section-title">✏️ Edit Movie</div>', unsafe_allow_html=True)

    if movies_df.empty:
        st.info("No movies to edit yet.")
        return

    search_q = st.text_input("🔍 Search for a movie to edit", placeholder="Start typing a title...")
    candidates = movies_df
    if search_q.strip():
        candidates = movies_df[movies_df["title"].astype(str).str.lower().str.contains(search_q.strip().lower())]

    if candidates.empty:
        st.warning("No movie matches that search.")
        return

    options = {f"{row['title']}  (ID {row['movie_id']})": row["movie_id"] for _, row in candidates.iterrows()}
    chosen_label = st.selectbox("Select movie", list(options.keys()))
    movie_id = options[chosen_label]
    row = movies_df[movies_df["movie_id"] == movie_id].iloc[0]

    st.markdown('<div class="admin-warning-box">⚠️ Watchlists, downloads, watch history and reviews '
               'reference movies by <b>title</b>, not ID. Renaming this movie means those existing '
               'references will no longer match it.</div>', unsafe_allow_html=True)

    col_left, col_right = st.columns([1, 2])
    with col_left:
        b64_path = POSTER_DIR / str(row["poster"])
        if row["poster"] and b64_path.exists():
            st.image(str(b64_path), width='stretch')
        else:
            st.caption("No poster on file for this movie.")

    with col_right:
        title = st.text_input("Title *", value=row["title"])
        existing_genres = sorted(movies_df["genre"].dropna().unique().tolist())
        current_genre_idx = existing_genres.index(row["genre"]) if row["genre"] in existing_genres else 0
        genre_choice = st.selectbox("Genre *", existing_genres + ["+ Add a new genre"], index=current_genre_idx)
        if genre_choice == "+ Add a new genre":
            genre = st.text_input("New genre name *")
        else:
            genre = genre_choice
        rating = st.number_input("Rating *", min_value=0.0, max_value=10.0,
                                 value=float(row["rating"]), step=0.1, format="%.1f")
        trailer_url = st.text_input("Trailer URL *", value=row["trailer"])

    st.markdown("**Replace poster** (optional)")
    new_poster_file = st.file_uploader("Upload a new poster image", type=["png", "jpg", "jpeg"], key="edit_poster_upload")
    manual_poster = st.text_input("...or type a filename already in poster/", value=str(row["poster"]))

    if st.button("💾 Save Changes", type="primary"):
        poster_filename = manual_poster.strip()
        if new_poster_file is not None:
            saved = save_uploaded_poster(new_poster_file, allow_overwrite=True)
            if saved:
                poster_filename = saved

        ok, msg = update_movie(movies_df, movie_id, title, genre, rating, poster_filename, trailer_url)
        if ok:
            st.success(f"✅ {msg}")
            st.rerun()
        else:
            st.error(f"❌ {msg}")


# ══════════════════════════════════════════════════════════
# DELETE MOVIE
# ══════════════════════════════════════════════════════════
def show_delete_movie(movies_df):
    st.markdown('<div class="section-title">🗑 Delete Movie</div>', unsafe_allow_html=True)

    if movies_df.empty:
        st.info("No movies to delete.")
        return

    search_q = st.text_input("🔍 Search for a movie to delete", placeholder="Start typing a title...")
    candidates = movies_df
    if search_q.strip():
        candidates = movies_df[movies_df["title"].astype(str).str.lower().str.contains(search_q.strip().lower())]

    if candidates.empty:
        st.warning("No movie matches that search.")
        return

    options = {f"{row['title']}  (ID {row['movie_id']})": row["movie_id"] for _, row in candidates.iterrows()}
    chosen_label = st.selectbox("Select movie", list(options.keys()), key="del_select")
    movie_id = options[chosen_label]
    row = movies_df[movies_df["movie_id"] == movie_id].iloc[0]

    st.markdown('<div class="admin-danger-box">', unsafe_allow_html=True)
    col_left, col_right = st.columns([1, 2])
    with col_left:
        b64_path = POSTER_DIR / str(row["poster"])
        if row["poster"] and b64_path.exists():
            st.image(str(b64_path), width='stretch')
    with col_right:
        st.markdown(f"""
        <div class="admin-info-row"><span>Title</span><b>{row['title']}</b></div>
        <div class="admin-info-row"><span>Genre</span><b>{row['genre']}</b></div>
        <div class="admin-info-row"><span>Rating</span><b>{row['rating']}</b></div>
        <div class="admin-info-row"><span>Movie ID</span><b>{row['movie_id']}</b></div>
        """, unsafe_allow_html=True)

    review_count = len(load_reviews_readonly().get(row["title"], []))
    if review_count:
        st.caption(f"ℹ️ This movie has {review_count} review(s) in reviews.json. "
                  "They will remain in reviews.json but will no longer be shown to users once deleted.")

    confirm = st.checkbox(f"I confirm I want to permanently delete '{row['title']}'")
    if st.button("🗑 Delete Permanently", type="primary", disabled=not confirm):
        ok, msg = delete_movie(movies_df, movie_id)
        if ok:
            st.success(f"✅ {msg}")
            st.rerun()
        else:
            st.error(f"❌ {msg}")
    st.markdown('</div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════
# REVIEWS & STATS
# ══════════════════════════════════════════════════════════
def show_reviews_page(reviews, movies_df):
    st.markdown('<div class="section-title">⭐ Reviews & Statistics</div>', unsafe_allow_html=True)

    if not reviews:
        st.info("No reviews in reviews.json yet.")
        return

    all_reviews = []
    for title, revs in reviews.items():
        for r in revs:
            all_reviews.append({**r, "movie": title})

    total = len(all_reviews)
    avg_rating = round(sum(r["stars"] for r in all_reviews) / total, 2) if total else 0

    c1, c2, c3 = st.columns(3)
    for col, (num, label) in zip([c1, c2, c3], [
        (str(total), "Total Reviews"),
        (str(avg_rating), "Average Rating"),
        (str(len(reviews)), "Movies Reviewed"),
    ]):
        col.markdown(f'<div class="stat-card"><div class="stat-number">{num}</div>'
                     f'<div class="stat-label">{label}</div></div>', unsafe_allow_html=True)

    st.markdown('<div class="neon-divider"></div>', unsafe_allow_html=True)
    st.markdown('<div class="section-title">🕓 Recent Reviews</div>', unsafe_allow_html=True)

    def _sort_key(r):
        try:
            return datetime.strptime(r["date"], "%d %b %Y")
        except Exception:
            return datetime.min

    for r in sorted(all_reviews, key=_sort_key, reverse=True)[:15]:
        st.markdown(f"""
        <div class="review-card">
            <span class="review-stars">{'⭐' * int(r['stars'])}</span>
            <b style="font-size:11px;">{r['user']}</b>
            <span style="font-size:9px;color:#8899bb;"> · {r['movie']} · {r['date']}</span>
            <div style="font-size:11px;color:#cbd5e1;margin-top:2px;">{r['text'] or '<i>No comment</i>'}</div>
        </div>""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════
# MAIN ENTRY POINT
# ══════════════════════════════════════════════════════════
def admin_page():
    """Call this from app.py to render the entire admin panel."""
    _inject_admin_css()

    if "admin_logged_in" not in st.session_state:
        st.session_state.admin_logged_in = False

    if not st.session_state.admin_logged_in:
        admin_login()
        return

    # ── Sidebar navigation ──
    st.sidebar.markdown('<div class="sidebar-logo">🛠️ Admin Panel</div>', unsafe_allow_html=True)
    st.sidebar.markdown('<span class="admin-badge-role">ADMIN MODE</span>', unsafe_allow_html=True)
    st.sidebar.markdown("---")

    if "admin_page_sel" not in st.session_state:
        st.session_state.admin_page_sel = "📊 Dashboard"

    for label in ["📊 Dashboard", "🎬 Movies", "➕ Add Movie", "✏️ Edit Movie",
                 "🗑 Delete Movie", "⭐ Reviews & Stats"]:
        btn_type = "primary" if st.session_state.admin_page_sel == label else "secondary"
        if st.sidebar.button(label, key=f"admin_nav_{label}", type=btn_type):
            st.session_state.admin_page_sel = label
            st.rerun()

    st.sidebar.markdown("---")
    if st.sidebar.button("🚪 Logout Admin"):
        st.session_state.admin_logged_in = False
        st.session_state.show_admin = False
        st.rerun()

    # ── Load data fresh on every render ──
    movies_df = load_movies()
    users     = load_users_readonly()
    reviews   = load_reviews_readonly()
    parties   = load_parties_readonly()
    likes     = load_likes_count_readonly()

    st.markdown("""
    <div class="hero-banner">
        <div class="hero-title">🛠️ NehaFlix — Admin Dashboard</div>
        <div class="hero-sub">Manage your movie catalog without touching movies.csv by hand.</div>
    </div>""", unsafe_allow_html=True)

    page = st.session_state.admin_page_sel
    if page == "📊 Dashboard":
        show_dashboard(movies_df, users, reviews, parties, likes)
    elif page == "🎬 Movies":
        show_movie_list(movies_df)
    elif page == "➕ Add Movie":
        show_add_movie(movies_df)
    elif page == "✏️ Edit Movie":
        show_edit_movie(movies_df)
    elif page == "🗑 Delete Movie":
        show_delete_movie(movies_df)
    elif page == "⭐ Reviews & Stats":
        show_reviews_page(reviews, movies_df)
