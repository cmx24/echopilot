class VoiceManager:
    def __init__(self):
        self.voice_profiles = {}
        self.metadata = {}

    def save_profile(self, profile_name, profile_data):
        """Saves a voice profile with the given name."""
        self.voice_profiles[profile_name] = profile_data
        self.metadata[profile_name] = {'timestamp': '2026-02-19 23:15:54 UTC'}

    def load_profile(self, profile_name):
        """Loads a voice profile by its name. Raises an exception if not found."""
        if profile_name not in self.voice_profiles:
            raise Exception(f"Profile '{profile_name}' not found.")
        return self.voice_profiles[profile_name]

    def get_metadata(self, profile_name):
        """Returns metadata for a specified voice profile."""
        return self.metadata.get(profile_name, 'No metadata available.')