# import logging
# from functools import lru_cache

# import b2sdk.v2 as b2sdk

# from app.config import config

# logger = logging.getLogger(__name__)


# @lru_cache
# # def get_b2_session() -> b2sdk.v2.B2Session:
# #     b2_session = b2sdk.v2.B2Session(
# #         application_id=config.b2.application_id,
# #         api_url_template=config.b2.api_url_template,
# #         user_agent_template=config.b2.user_agent_template,
# #     )

#     b2_session.authenticate(
#         application_key=config.b2.application_key,
#         application_key_id=config.b2.application_key_id,
#     )

#     return b2_session