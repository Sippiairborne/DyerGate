import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.models import (
    MarketplaceListing, MarketplaceInstall, MarketplaceReview,
    AgentSkill, ClientAccount, Organization,
)

logger = logging.getLogger("dyergate.storefront")


def create_listing(
    db: Session, skill: AgentSkill, title: str,
    tagline: str = None, long_description: str = None,
    categories: str = None, screenshots: list = None,
) -> MarketplaceListing:
    listing = MarketplaceListing(
        skill_id=skill.id, title=title, tagline=tagline,
        long_description=long_description, categories=categories,
        screenshots=screenshots or [], is_featured=False,
    )
    db.add(listing); db.commit(); db.refresh(listing)
    return listing


def browse(
    db: Session, category: str = None, search: str = None,
    sort_by: str = "popular", limit: int = 50,
) -> list[dict]:
    q = db.query(MarketplaceListing).join(AgentSkill).filter(
        AgentSkill.is_approved == True, AgentSkill.is_active == True,
    )
    if category:
        q = q.filter(MarketplaceListing.categories.contains(category))
    if search:
        q = q.filter(MarketplaceListing.title.ilike(f"%{search}%"))
    if sort_by == "popular":
        q = q.order_by(MarketplaceListing.install_count.desc())
    elif sort_by == "rating":
        q = q.order_by(MarketplaceListing.rating_avg.desc())
    elif sort_by == "newest":
        q = q.order_by(MarketplaceListing.created_at.desc())
    rows = q.limit(min(limit, 200)).all()
    return [{
        "id": r.id, "title": r.title, "tagline": r.tagline,
        "categories": r.categories.split(",") if r.categories else [],
        "install_count": r.install_count,
        "rating_avg": r.rating_avg, "rating_count": r.rating_count,
        "is_featured": r.is_featured,
        "skill_slug": r.skill.slug, "skill_name": r.skill.name,
        "cost_per_invocation": r.skill.cost_per_invocation,
    } for r in rows]


def install(db: Session, listing_id: int, org: Organization) -> MarketplaceInstall:
    existing = db.query(MarketplaceInstall).filter(
        MarketplaceInstall.listing_id == listing_id, MarketplaceInstall.org_id == org.id,
    ).first()
    if existing:
        return existing
    inst = MarketplaceInstall(listing_id=listing_id, org_id=org.id)
    db.add(inst)
    listing = db.query(MarketplaceListing).filter(MarketplaceListing.id == listing_id).first()
    if listing:
        listing.install_count += 1
    db.commit()
    db.refresh(inst)
    return inst


def uninstall(db: Session, listing_id: int, org: Organization) -> bool:
    inst = db.query(MarketplaceInstall).filter(
        MarketplaceInstall.listing_id == listing_id, MarketplaceInstall.org_id == org.id,
    ).first()
    if not inst:
        return False
    db.delete(inst)
    listing = db.query(MarketplaceListing).filter(MarketplaceListing.id == listing_id).first()
    if listing and listing.install_count > 0:
        listing.install_count -= 1
    db.commit()
    return True


def review(db: Session, listing_id: int, org: Organization,
           rating: int, comment: str = None) -> MarketplaceReview:
    if not 1 <= rating <= 5:
        raise ValueError("Rating must be 1-5.")
    rv = MarketplaceReview(listing_id=listing_id, org_id=org.id,
                          rating=rating, comment=comment)
    db.add(rv); db.commit()
    listing = db.query(MarketplaceListing).filter(MarketplaceListing.id == listing_id).first()
    if listing:
        total = listing.rating_avg * listing.rating_count + rating
        listing.rating_count += 1
        listing.rating_avg = total / listing.rating_count
        db.commit()
    return rv
