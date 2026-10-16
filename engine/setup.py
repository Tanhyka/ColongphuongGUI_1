"""Setup decisions independent of board rendering and game rules."""
from .pieces import Player

def bottom_for_setup(config):
    cam=str(config.get('cam_controller','Human')).strip().lower()=='human'
    xanh=str(config.get('xanh_controller','Human')).strip().lower()=='human'
    if cam != xanh:
        return Player.CAM if cam else Player.XANH
    return None  # Keep manual orientation for human/human or engine/engine.

def flipped_for_bottom(player):
    if not isinstance(player,Player):raise ValueError('Bottom side must be CAM or XANH')
    # Logical CAM home row is 0. Only the view is rotated.
    return player is Player.CAM
