from dataclasses import dataclass
from typing import Dict, Any, Optional

@dataclass
class Prompt:
    name: str
    template: str
    description: Optional[str] = None
    display_name: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'name': self.name,
            'template': self.template,
            'description': self.description,
            'display_name': self.display_name
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Prompt':
        # Validate required fields
        required_fields = ['name', 'template']
        missing_fields = [field for field in required_fields if field not in data]
        
        if missing_fields:
            raise ValueError(f"Missing required fields: {', '.join(missing_fields)}")
            
        # Validate field types
        if not isinstance(data['name'], str):
            raise ValueError("'name' must be a string")
        if not isinstance(data['template'], str):
            raise ValueError("'template' must be a string")
            
        return cls(
            name=data['name'],
            template=data['template'],
            description=data.get('description'),
            display_name=data.get('display_name')
        ) 